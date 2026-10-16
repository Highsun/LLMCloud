"""Run with training dependencies: uv run --locked --extra training python scripts/check_gpu.py."""

import sys

try:
    import torch
except ImportError:
    sys.exit("PyTorch 尚未安装；请先按照 README 准备训练环境。")

print(f"PyTorch: {torch.__version__}; CUDA runtime: {torch.version.cuda}")
if not torch.cuda.is_available():
    sys.exit("CUDA 不可用；请检查 Windows NVIDIA 驱动和 WSL GPU 透传。")
print(f"GPU: {torch.cuda.get_device_name(0)}")
print(f"Compute capability: {torch.cuda.get_device_capability(0)}")
print(f"Wheel architectures: {torch.cuda.get_arch_list()}")
# Execute a real kernel; cuda.is_available() alone is not a compatibility check.
x = torch.randn(256, 256, device="cuda", requires_grad=True)
loss = (x @ x).square().mean()
loss.backward()
torch.cuda.synchronize()
if not torch.isfinite(loss).item() or not torch.isfinite(x.grad).all().item():
    sys.exit("GPU 前向/反向计算结果异常。")
print("GPU 前向与反向计算通过。")
