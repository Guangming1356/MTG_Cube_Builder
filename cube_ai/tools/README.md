# 开发辅助工具

- `build_portable.py`、`compile_portable.ps1`、`portable_entry.pyw`、`PortableBootstrap.cs`：制作含独立运行环境的 Windows 便携版。
- `benchmark_search.py`：从测试夹具比较完整候选评估的串行、增量与并行结果，输出到本机 private/benchmarks。
- `cleanup_local.ps1`：维护者本机的清理入口，依赖本机清单和发布验收记录；没有这些文件时停止，不会清理别人的数据。

日常使用从快捷方式进入，不需要运行这些工具。程序中的一键机器测速、任务控制和 Forge 对局功能都保留。一次性历史版本迁移、硬编码旧任务的验收脚本和对应迁移测试已删除，历史标签仍可取回。

## 构建依赖

本机清理包含构建缓存。再次制作便携包前，需要重新准备 build_portable.py 中固定版本及校验值对应的 CPython 嵌入式 ZIP、Windows Python wheels、Forge 和 OpenJDK 对应源码压缩包，放入 `发布包/构建缓存`。本机主程序保留的 Forge/Java/NVRTC、卡牌快照和知识库也需齐全。

从 GitHub 源码开始的开发者先按仓库 README 使用 setup_dev.py 恢复运行依赖；这一步不等于恢复全部打包依赖。历史便携包可以直接从 Releases 下载使用。

## 本轮新增的可复用工具

- `benchmark_hotpaths.py`：以原全库载入和增量载入作 ABBA 比较，报告候选进程的真实内存、耗时及结果一致性。输出保存在 private，不调用 AI。
- `repackage_release.py`：核验旧便携包 SHA256 后，仅更新应用代码、网页和公共文档。保留独立运行环境、许可证及对应源码；桥接 Java 或依赖改变时拒绝复用，改用完整构建。
- `verify_portable_release.py`：在 Windows 的全新解压副本中，使用内置 Python 验证启动、离线模式、轮抓、暂停/继续、退出保护和重启后恢复。验收副本不会再次打包。

GitHub 中的“Build verified Windows release”工作流可按需生成完整便携版，验收并核对远端附件后才正式发布；本机不需要长期保留发布包。

完整构建须显式传入 `--version YYYYMMDD`；先运行 build_portable.py 生成暂存目录，再用 compile_portable.ps1 编译入口，最后以同一版本号传入 `--package <目录>`。缺缓存时会在复制运行环境前停止。
