先给你两个关键结论，然后把 Ninja 路线的可落地修复一步步给全（VS 生成器那条你已经写得很完整了）。

关键结论（你现在卡住的根因）

SM=120 是无效/过时的架构编号
CUDA 的 CMAKE_CUDA_ARCHITECTURES 使用的是 Compute Capability（如 80/86/89/90 …），不是“12.0=120”。
RTX 50/40 系（Ada）对应 8.9（即 89），Hopper 是 90。请把 120 改成 89（或按需做 fatbin：89;90）。
cmake.org
+2
NVIDIA Docs
+2

Ninja+MSVC 下 NVCC 的 “A single input file is required …” 基本都是引号与 /Fd /FS 等 MSVC PDB 参数通过 -Xcompiler 透传时被拆分
这是 CMake/NVCC 在 Windows 命令行与响应文件处理上的老坑，社区里有相同症状的讨论与已归档 issue。
NVIDIA Developer Forums
+1

方案 B：Ninja 路线的最小改动修复（推荐你现在这么做）

目标： 在 Ninja+MSVC 下，避免向 NVCC 透传会触发拆分的 PDB 相关参数，从源头上消除 -Xcompiler "/Fd..., /FS"。

1) 统一改对架构
-DCMAKE_CUDA_ARCHITECTURES=89


（Ada/RTX 5090D ≈ 8.9）。
cmake.org
+2
NVIDIA Docs
+2

2) 关闭/改用“嵌入式”调试信息，杜绝 /Fd 注入

CMake 3.25+ 提供 MSVC_DEBUG_INFORMATION_FORMAT。给 所有含 CUDA 的目标设置为 Embedded（等价 /Z7，不会生成 .pdb，也就不会有 /Fd 路径被透传）：

# CMakeLists.txt 顶部全局开关（覆盖 Debug/RelWithDebInfo）
set(CMAKE_MSVC_DEBUG_INFORMATION_FORMAT "Embedded")  # /Z7

# 如果你只想在 Debug/RelWithDebInfo 生效（示例：项目级）
set_property(TARGET va_cuda_kernels PROPERTY
  MSVC_DEBUG_INFORMATION_FORMAT "$<$<CONFIG:Debug,RelWithDebInfo>:Embedded>")


变量与属性文档：CMAKE_MSVC_DEBUG_INFORMATION_FORMAT 与 MSVC_DEBUG_INFORMATION_FORMAT。
cmake.org
+1

这样做后，CMake 不会再给 MSVC/NVCC 注入 /Zi + /Fd...；也不需要你的 nvcc_wrap.py 去删 -Xcompiler="/Fd...,/FS"，直接避免了引号拆分这一触发条件。

3) 升一下 CMake（若你 < 3.27/3.28）

较新 CMake 对 CUDA + Ninja 的响应文件/引号处理更稳（社区在 3.27+/3.28+ 有多次相关修复）。若当前版本偏旧，建议升到 3.29+。
GitHub

4) 用 Ninja Multi-Config（可选，但在 MSVC 场景更稳）

生成器改为：

-G "Ninja Multi-Config"


它在 Windows/MSVC 下经常比单配置 Ninja 更“像 VS”，减少奇怪 flag 组合带来的边角问题。（常识性建议，配合上面的 /Z7 更干净。）

5) 最终一次性配置与构建命令样例
cmake -S D:\Projects\ai\cv\video-analyzer ^
  -B D:\Projects\ai\cv\video-analyzer\build-ninja ^
  -G "Ninja Multi-Config" ^
  -DCMAKE_BUILD_TYPE=Release ^
  -DWITH_CUDA_KERNELS=ON ^
  -DCMAKE_CUDA_ARCHITECTURES=89 ^
  -DOpenCV_DIR=H:\opencv\build\x64\vc16\lib

cmake --build D:\Projects\ai\cv\video-analyzer\build-ninja --config Release --target va_cuda_kernels
cmake --build D:\Projects\ai\cv\video-analyzer\build-ninja --config Release --target VideoAnalyzer

如果你坚持 Zi/PDB（仍想要 .pdb）：两条替代思路

只对 CUDA 目标改为 Embedded（/Z7），其他 C++ 目标保留 /Zi。这样 CUDA 不产 .pdb，其余模块仍有 .pdb。见上面的 target 级 set_property。
cmake.org

走 VS 生成器专编内核（你写的“方案 A/混合法”）：
把 va_cuda_kernels 用 VS 生成器（安装好 BuildCustomizations 后）单独编出，Ninja 负责编链其他目标。NV 的 VS 集成（install_cuda.vbs -> CUDA 12.9.props）就是为此提供的 MSBuild 属性与 task。
NVIDIA Docs