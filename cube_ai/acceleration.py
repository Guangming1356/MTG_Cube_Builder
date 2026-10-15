"""Small optional CUDA backend; NumPy remains the measured fallback."""
import ctypes as C
import os
import threading
import time
from pathlib import Path
import numpy as np
from .forge_setup import RUNTIME

KERNEL=r'''
extern "C" __global__ void linear(const float* x,const float* w,float* y,int n,int f,int m){
  __shared__ float a[16][16], b[16][16];
  int tx=threadIdx.x,ty=threadIdx.y,row=blockIdx.y*16+ty,col=blockIdx.x*16+tx;
  float value=0;
  for(int k0=0;k0<f;k0+=16){
    int k=k0+tx,wr=blockIdx.x*16+ty;
    a[ty][tx]=(row<n && k<f)?x[row*f+k]:0;
    b[ty][tx]=(wr<m && k<f)?w[wr*f+k]:0;
    __syncthreads();
    for(int k1=0;k1<16;k1++)value+=a[ty][k1]*b[tx][k1];
    __syncthreads();
  }
  if(row<n && col<m)y[row*m+col]=value;
}'''

class CUDAError(RuntimeError):pass

def driver_info():
    if os.name!='nt':return dict(available=False,reason='当前轻量 CUDA 适配支持 Windows NVIDIA 驱动')
    try:
        driver=C.WinDLL('nvcuda.dll');code=driver.cuInit(0)
        if code:raise CUDAError(f'CUDA 初始化代码 {code}')
        name=C.create_string_buffer(256);device=C.c_int();version=C.c_int()
        if driver.cuDeviceGet(C.byref(device),0):raise CUDAError('没有可用 NVIDIA 计算设备')
        driver.cuDeviceGetName(name,256,device);driver.cuDriverGetVersion(C.byref(version))
        return dict(available=True,device=name.value.decode('utf8'),driver=version.value,
            compiler_available=bool(list((RUNTIME/'acceleration').glob('nvrtc64_*.dll'))))
    except (OSError,CUDAError) as e:return dict(available=False,reason=str(e))

class CUDALinear:
    def __init__(self):
        folder=(RUNTIME/'acceleration').resolve()
        nvrtcs=list(folder.glob('nvrtc64_*.dll'))
        if not nvrtcs:raise CUDAError('尚未安装 NVRTC 评分组件')
        self.dll_dir=os.add_dll_directory(str(folder));self.driver=C.WinDLL('nvcuda.dll')
        def fn(name,args):
            value=getattr(self.driver,name);value.argtypes=args;value.restype=C.c_int;return value
        P=C.c_void_p;U=C.c_uint;I=C.c_int;S=C.c_size_t;D=C.c_ulonglong
        self.init=fn('cuInit',[U]);self.get_device=fn('cuDeviceGet',[C.POINTER(I),I])
        self.create=fn('cuCtxCreate_v2',[C.POINTER(P),U,I]);self.set_context=fn('cuCtxSetCurrent',[P])
        self.destroy=fn('cuCtxDestroy_v2',[P]);self.module_load=fn('cuModuleLoadData',[C.POINTER(P),P])
        self.get_function=fn('cuModuleGetFunction',[C.POINTER(P),P,C.c_char_p])
        self.alloc=fn('cuMemAlloc_v2',[C.POINTER(D),S]);self.free=fn('cuMemFree_v2',[D])
        self.to_gpu=fn('cuMemcpyHtoD_v2',[D,P,S]);self.from_gpu=fn('cuMemcpyDtoH_v2',[P,D,S])
        self.launch=fn('cuLaunchKernel',[P,U,U,U,U,U,U,U,P,C.POINTER(P),P])
        self.check(self.init(0));device=I();self.check(self.get_device(C.byref(device),0))
        self.context=P();self.check(self.create(C.byref(self.context),0,device));self.buffers=[]
        self.builtins=[C.CDLL(str(p)) for p in folder.glob('nvrtc-builtins*.dll')]
        rtc=C.CDLL(str(nvrtcs[0]));self.rtc=rtc;program=P()
        rtc.nvrtcCreateProgram.argtypes=[C.POINTER(P),C.c_char_p,C.c_char_p,I,P,P]
        rtc.nvrtcCompileProgram.argtypes=[P,I,C.POINTER(C.c_char_p)]
        rtc.nvrtcGetPTXSize.argtypes=[P,C.POINTER(S)];rtc.nvrtcGetPTX.argtypes=[P,P]
        rtc.nvrtcGetProgramLogSize.argtypes=[P,C.POINTER(S)];rtc.nvrtcGetProgramLog.argtypes=[P,P]
        rtc.nvrtcDestroyProgram.argtypes=[C.POINTER(P)]
        self.check(rtc.nvrtcCreateProgram(C.byref(program),KERNEL.encode(),b'cube_linear.cu',0,None,None))
        # Forward-compatible PTX; the installed driver JIT targets the actual GPU.
        options=(C.c_char_p*2)(b'--gpu-architecture=compute_75',b'--fmad=false')
        code=rtc.nvrtcCompileProgram(program,2,options)
        if code:
            size=S();rtc.nvrtcGetProgramLogSize(program,C.byref(size));log=C.create_string_buffer(size.value)
            rtc.nvrtcGetProgramLog(program,log);rtc.nvrtcDestroyProgram(C.byref(program))
            raise CUDAError(log.value.decode('utf8',errors='replace'))
        size=S();self.check(rtc.nvrtcGetPTXSize(program,C.byref(size)));ptx=C.create_string_buffer(size.value)
        self.check(rtc.nvrtcGetPTX(program,ptx));rtc.nvrtcDestroyProgram(C.byref(program))
        self.module=P();self.check(self.module_load(C.byref(self.module),C.cast(ptx,P)))
        self.function=P();self.check(self.get_function(C.byref(self.function),self.module,b'linear'))

    @staticmethod
    def check(code):
        if code:raise CUDAError(f'CUDA/NVRTC 调用失败，代码 {code}')

    def linear(self,x,w):
        x=np.ascontiguousarray(x,dtype=np.float32);w=np.ascontiguousarray(w.T,dtype=np.float32)
        n,f=x.shape;m=w.shape[0]
        if w.shape[1]!=f:raise ValueError('评分矩阵维度不一致')
        if not n or not m:return np.zeros((n,m),dtype=np.float32)
        self.check(self.set_context(self.context))
        sizes=[x.nbytes,w.nbytes,n*m*4]
        while len(self.buffers)<3:self.buffers.append([C.c_ulonglong(),0])
        for slot,size in zip(self.buffers,sizes):
            if slot[1]<size:
                if slot[1]:self.check(self.free(slot[0]))
                self.check(self.alloc(C.byref(slot[0]),size));slot[1]=size
        dx,dw,dy=[v[0] for v in self.buffers]
        self.check(self.to_gpu(dx,C.c_void_p(x.ctypes.data),x.nbytes));self.check(self.to_gpu(dw,C.c_void_p(w.ctypes.data),w.nbytes))
        ni,fi,mi=C.c_int(n),C.c_int(f),C.c_int(m)
        values=[dx,dw,dy,ni,fi,mi];params=(C.c_void_p*6)(*[C.cast(C.byref(v),C.c_void_p) for v in values])
        self.check(self.launch(self.function,(m+15)//16,(n+15)//16,1,16,16,1,0,None,params,None))
        result=np.empty((n,m),dtype=np.float32)
        self.check(self.from_gpu(C.c_void_p(result.ctypes.data),dy,result.nbytes))
        return result

_lock=threading.RLock();_cuda=None;_failure=None;_choices={}

def linear(x,w,backend='auto'):
    """Choose on end-to-end timings, including copies; disclose fallback."""
    global _cuda,_failure
    if backend not in {'auto','cpu','gpu'}:raise ValueError('评分后端需为 auto、cpu 或 gpu')
    x=np.ascontiguousarray(x,dtype=np.float32);w=np.ascontiguousarray(w,dtype=np.float32)
    if x.ndim!=2 or w.ndim!=2 or x.shape[1]!=w.shape[0]:raise ValueError('评分矩阵维度不一致')
    with _lock:
        key=(len(x).bit_length(),x.shape[1],w.shape[1])
        if _cuda is not None and not _failure and backend!='cpu' and key in _choices and (backend=='gpu' or _choices[key]=='gpu'):
            try:
                started=time.perf_counter();value=_cuda.linear(x,w)
                return value,dict(backend='gpu',gpu_seconds=time.perf_counter()-started,rows=len(x),requested=backend,calibrated=True)
            except (CUDAError,OSError,AttributeError) as e:_failure=str(e)
        started=time.perf_counter();cpu=x@w;cpu_seconds=time.perf_counter()-started
        meta=dict(backend='cpu',cpu_seconds=cpu_seconds,rows=len(x),requested=backend)
        if backend=='cpu' or backend=='auto' and x.size*w.shape[1]<2_000_000:return cpu,meta
        if _failure:return cpu,dict(meta,fallback=_failure)
        try:
            if key not in _choices:
                timings=[]
                for _ in range(3):
                    started=time.perf_counter();cpu=x@w;timings.append(time.perf_counter()-started)
                cpu_seconds=float(np.median(timings));meta['cpu_seconds']=cpu_seconds
            if _cuda is None:_cuda=CUDALinear()
            if backend=='auto' and _choices.get(key)=='cpu':return cpu,meta
            timings=[]
            for _ in range(3):
                started=time.perf_counter();gpu=_cuda.linear(x,w);timings.append(time.perf_counter()-started)
            gpu_seconds=float(np.median(timings))
            error=float(np.max(np.abs(gpu-cpu))) if cpu.size else 0.0
            if not np.allclose(gpu,cpu,rtol=2e-4,atol=2e-4):raise CUDAError('GPU 与 CPU 评分超出容差')
            selected='gpu' if backend=='gpu' or gpu_seconds<cpu_seconds*.9 else 'cpu'
            _choices[key]='gpu' if gpu_seconds<cpu_seconds*.9 else 'cpu'
            return (gpu if selected=='gpu' else cpu),dict(meta,backend=selected,gpu_seconds=gpu_seconds,max_error=error)
        except (CUDAError,OSError,AttributeError) as e:
            _failure=str(e);return cpu,dict(meta,fallback=_failure)

def status():
    return dict(driver_info(),selected_shapes=len(_choices),failure=_failure)
