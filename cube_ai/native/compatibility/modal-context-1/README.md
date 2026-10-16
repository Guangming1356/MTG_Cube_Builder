# 模式咒语说明上下文兼容组件

这是针对指定 Forge 2.0.15 JAR 的独立覆盖类，许可证为 GPL-3.0-or-later，见同目录 `LICENSE.txt`。原 Forge JAR 和 `CubeWorker.java` 均不修改。关闭网页“对局兼容修复”即可使用原始引擎。

## 修复范围

Forge 的 `CharmEffect.makeFormatedDescription(SpellAbility, boolean)` 会先枚举模式选项、再补充缺失的施放者；枚举目标时可能已访问空施放者。组件把有条件的初始化提前到该说明方法入口：仅在施放者为空且来源卡牌有控制者时设置来源控制者。已有施放者不覆盖。其他八个方法的全部字节属性保持原样；没有修改结算、模式选择或目标合法性方法。

这仍可能改变原本有缺失上下文的 AI 路径。验证覆盖固定牌组与种子，不能保证所有牌和所有未来 Forge 版本。引擎警告和其余异常仍原样报告。此组件不代表 Forge 官方修复。

## 可复现构建

`build/dependencies.json` 记录原 JAR、原类、变换器源码、预期类以及 ECJ/ASM 构建依赖的精确 SHA256 和公开 Maven Central 来源。依赖仅用于开发重建；运行助手不需要下载编译器、ASM 或反编译器。

使用 Python 3.11+、Java 21，准备校验匹配的原 Forge JAR、ECJ 与 ASM 文件后，在本目录运行（各路径替换为自己电脑的实际路径）：

```text
python build/build.py --java JAVA_EXE --ecj ECJ_JAR --asm ASM_JAR --forge FORGE_JAR --out NEW_EMPTY_FOLDER
```

构建器先检查依赖与原类哈希，再要求不修改的字节码往返与原文件完全相同，核对仅一个说明方法改变，并检查输出精确匹配已审阅类。ASM 可重排类级属性，构建器核对内容完全相同后恢复原顺序。输出为 `classes/…/CharmEffect.class` 和构建证明；不会改写输入 JAR，也不会覆盖已有输出。

`manifest.json` 发布记录用于标明实际验证范围，包含对应源码文件的校验值。应用只接受内置的已审阅清单与类；缺失、改动或 Forge 版本不匹配时不加载覆盖类。

Forge 上游及完整对应源码随便携版保留，来源为 `https://github.com/Card-Forge/forge/tree/forge-2.0.15`。变换器源码及本构建器随组件提供；没有分发开发时的反编译输出。
