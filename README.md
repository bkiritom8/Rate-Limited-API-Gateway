# Cross-Platform PyTorch Training System

A production-ready PyTorch training framework designed to work seamlessly across **CUDA (NVIDIA GPUs)**, **MPS (Apple Silicon)**, and **CPU** backends with zero platform-specific code.

## Architecture Overview

This system consists of four main components:

### 1. **Device Management (`device_utils.py`)**
- Automatic device detection with priority: CUDA > MPS > CPU
- Cross-platform device operations (synchronization, memory management)
- Safe fallback mechanisms for unsupported operations
- Detailed device logging and memory statistics

### 2. **Neural Network Models (`model.py`)**
- `ConvolutionalClassifier`: Simple CNN for image classification
- `SimpleResNet`: Residual network with skip connections
- Both models are fully compatible with all backends
- Efficient architecture with minimal parameters

### 3. **Training Framework (`trainer.py`)**
- Universal training loop with automatic device placement
- Built-in validation and evaluation
- Checkpoint saving and loading
- Early stopping support
- Comprehensive metrics tracking
- Cross-platform memory management

### 4. **Main Application (`main.py`)**
- Command-line interface for easy configuration
- Synthetic data generation for demonstration
- Complete training pipeline with evaluation
- Configurable hyperparameters

## Features

- **Zero Platform-Specific Code**: Single codebase runs on all platforms
- **Automatic Device Detection**: Intelligent selection of best available accelerator
- **Robust Error Handling**: Graceful degradation and meaningful error messages
- **Memory Efficient**: Automatic cache clearing and memory tracking
- **Production Ready**: Logging, checkpointing, and monitoring built-in
- **Extensible**: Clean architecture for adding new models and features

## Installation

### Quick Setup (Automated)

**macOS:**
```bash
git clone <your-repo-url>
cd test
./setup_mac.sh
```

**Windows:**
```powershell
git clone <your-repo-url>
cd test
.\setup_windows.ps1
```

The setup scripts will automatically create a virtual environment, install PyTorch with the correct backend, and verify the installation.

### Manual Setup

#### Apple Silicon (MPS)

```bash
# Clone the repository
git clone <your-repo-url>
cd test

# Ensure you have Python 3.8+ installed
python3 -m venv venv
source venv/bin/activate

# Install PyTorch with MPS support (note the quotes to prevent shell interpretation)
pip install "torch>=2.0.0"

# Or install from requirements.txt
pip install -r requirements.txt
```

#### Windows with NVIDIA GPU (CUDA)

```powershell
# Clone the repository
git clone <your-repo-url>
cd test

# Ensure you have Python 3.8+ installed
python -m venv venv
venv\Scripts\activate

# Install PyTorch with CUDA support (example for CUDA 11.8)
pip install torch torchvision --index-url https://download.pytorch.org/whl/cu118

# For CUDA 12.1:
# pip install torch torchvision --index-url https://download.pytorch.org/whl/cu121

# Alternatively, visit https://pytorch.org to get the appropriate command for your CUDA version
```

#### CPU-Only (Any Platform)

```bash
# Create virtual environment
python -m venv venv

# Activate (macOS/Linux)
source venv/bin/activate

# Activate (Windows)
venv\Scripts\activate

# Install PyTorch
pip install torch
```

## Usage

### Basic Training

```bash
# Auto-detect device and train for 10 epochs
python main.py

# Train for 20 epochs
python main.py --epochs 20

# Use ResNet model instead of CNN
python main.py --model resnet

# Force CPU mode (useful for testing)
python main.py --cpu
```

### Advanced Options

```bash
# Custom hyperparameters
python main.py \
    --epochs 30 \
    --batch-size 128 \
    --learning-rate 0.0001 \
    --model resnet

# Larger dataset
python main.py \
    --num-train 5000 \
    --num-val 1000 \
    --num-test 500

# Verbose logging
python main.py --verbose

# Custom checkpoint directory
python main.py --checkpoint-dir ./my_checkpoints
```

### Command-Line Arguments

| Argument | Type | Default | Description |
|----------|------|---------|-------------|
| `--cpu` | flag | False | Force CPU usage |
| `--epochs` | int | 10 | Number of training epochs |
| `--batch-size` | int | 64 | Batch size for training |
| `--learning-rate` | float | 0.001 | Learning rate |
| `--model` | str | cnn | Model architecture (cnn or resnet) |
| `--checkpoint-dir` | str | checkpoints | Checkpoint directory |
| `--verbose` | flag | False | Enable verbose logging |
| `--num-train` | int | 1000 | Number of training samples |
| `--num-val` | int | 200 | Number of validation samples |
| `--num-test` | int | 200 | Number of test samples |

## Running on Multiple Machines Concurrently

You can run training on both your Mac and PC simultaneously to compare performance across different hardware accelerators (MPS vs CUDA).

### Option 1: Independent Training Runs (Recommended for Testing)

Run completely separate training sessions on each machine:

**On Mac (MPS):**
```bash
# Clone and setup
git clone <your-repo-url>
cd test
python3 -m venv venv
source venv/bin/activate
pip install "torch>=2.0.0"

# Run with MPS-specific checkpoint directory
python main.py --checkpoint-dir ./checkpoints_mac --epochs 20
```

**On Windows PC (CUDA):**
```powershell
# Clone and setup
git clone <your-repo-url>
cd test
python -m venv venv
venv\Scripts\activate
pip install torch --index-url https://download.pytorch.org/whl/cu118

# Run with CUDA-specific checkpoint directory
python main.py --checkpoint-dir ./checkpoints_pc --epochs 20
```

This allows you to:
- Compare training speeds (epochs/sec) between MPS and CUDA
- Verify identical behavior across platforms
- Test different hyperparameters on each machine

### Option 2: Shared Checkpoints via Cloud Storage

To resume training across machines using shared checkpoints:

**Setup:**
```bash
# On both machines, use a cloud-synced directory (Dropbox, Google Drive, OneDrive, etc.)
# macOS example:
python main.py --checkpoint-dir ~/Dropbox/pytorch_checkpoints

# Windows example:
python main.py --checkpoint-dir "C:\Users\YourName\Dropbox\pytorch_checkpoints"
```

**Workflow:**
1. Start training on Mac, let it run for 10 epochs
2. Cloud service syncs checkpoints automatically
3. Stop training on Mac
4. Continue on PC by loading the checkpoint:

```python
# Add to main.py to resume from checkpoint
from pathlib import Path

checkpoint_path = Path("path/to/best_model.pt")
if checkpoint_path.exists():
    trainer.load_checkpoint(checkpoint_path)
```

### Option 3: Git-Based Checkpoint Sharing

Share checkpoints via Git LFS (for smaller models):

```bash
# Install Git LFS (one-time setup)
git lfs install
git lfs track "*.pt"

# On Mac - train and commit checkpoints
python main.py --epochs 10
git add checkpoints/
git commit -m "Training checkpoint after 10 epochs on MPS"
git push

# On PC - pull and continue
git pull
python main.py --epochs 20  # Will continue if you add resume logic
```

### Performance Comparison Tips

To fairly compare MPS vs CUDA performance:

```bash
# Run identical configurations
# Mac:
python main.py --epochs 10 --batch-size 64 --model resnet --verbose

# PC:
python main.py --epochs 10 --batch-size 64 --model resnet --verbose

# Compare the "Time: X.XXs" per epoch in the logs
```

Expected performance characteristics:
- **CUDA (high-end NVIDIA)**: Fastest training, best for large models
- **MPS (M-series Mac)**: Good performance, excellent power efficiency
- **CPU**: Slowest, but guaranteed compatibility

## Platform-Specific Notes

### Apple Silicon (M1/M2/M3)

- MPS acceleration is automatically detected and enabled
- Requires PyTorch 2.0 or later for stable MPS support
- Some operations may fall back to CPU if not yet optimized for MPS
- Pin memory is disabled for MPS compatibility

### NVIDIA GPUs (CUDA)

- Automatic GPU selection if multiple GPUs available
- Memory statistics and monitoring enabled
- Cache clearing for optimal memory usage
- Full support for all PyTorch operations

### CPU Fallback

- Automatically used when no accelerator is available
- Warning logged to inform about potentially slower training
- Identical behavior to GPU modes (just slower)
- Useful for testing and development

## Code Structure

```
.
├── main.py              # Entry point and CLI
├── device_utils.py      # Device detection and management
├── model.py             # Neural network architectures
├── trainer.py           # Training and evaluation logic
├── requirements.txt     # Python dependencies
├── setup_mac.sh         # Automated setup for macOS (MPS)
├── setup_windows.ps1    # Automated setup for Windows (CUDA)
└── README.md            # This file
```

## Extending the System

### Adding a New Model

```python
# In model.py
class MyCustomModel(nn.Module):
    def __init__(self, input_channels: int, num_classes: int):
        super(MyCustomModel, self).__init__()
        # Define your layers here

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        # Define forward pass
        return x

    def get_num_parameters(self) -> int:
        return sum(p.numel() for p in self.parameters() if p.requires_grad)
```

### Using Real Datasets

Replace the `create_data_loaders()` function in `main.py`:

```python
from torchvision import datasets, transforms

def create_data_loaders(batch_size: int = 64):
    transform = transforms.Compose([
        transforms.ToTensor(),
        transforms.Normalize((0.5,), (0.5,))
    ])

    train_dataset = datasets.MNIST(
        root='./data',
        train=True,
        download=True,
        transform=transform
    )

    train_loader = DataLoader(
        train_dataset,
        batch_size=batch_size,
        shuffle=True,
        num_workers=0
    )

    return train_loader, val_loader, test_loader
```

## Performance Tips

1. **Batch Size**: Increase batch size for better GPU utilization
2. **Data Loading**: Set `num_workers=0` for cross-platform compatibility
3. **Memory**: Monitor memory usage with `--verbose` flag
4. **Mixed Precision**: Can be added for CUDA GPUs (not supported on MPS yet)

## Troubleshooting

### Shell Parsing Errors (zsh: not found)

If you get `zsh: 2.0.0 not found` or similar errors on macOS:

```bash
# WRONG (shell interprets >= as redirection):
pip install torch>=2.0.0

# CORRECT (use quotes):
pip install "torch>=2.0.0"

# Or just install latest:
pip install torch
```

The `>=` operator is interpreted by zsh/bash as a shell redirection operator. Always quote package specifications with comparison operators.

### Files Not Found After Git Clone

If `python main.py` says file not found:

```bash
# Make sure you're on the correct branch
git branch

# Checkout the feature branch
git checkout claude/cross-platform-python-setup-Apsdv

# Verify files exist
ls -l *.py

# You should see: device_utils.py, main.py, model.py, trainer.py
```

### MPS Issues

If MPS is detected but fails:
```bash
# Force CPU mode
python main.py --cpu

# Check MPS availability
python -c "import torch; print(f'MPS available: {torch.backends.mps.is_available()}')"
```

### CUDA Out of Memory

```bash
# Reduce batch size
python main.py --batch-size 32

# Reduce dataset size
python main.py --num-train 500

# Check GPU memory
nvidia-smi
```

### Import Errors

```bash
# Verify PyTorch installation
python -c "import torch; print(torch.__version__)"

# Check device detection
python -c "import torch; print('CUDA:', torch.cuda.is_available()); print('MPS:', torch.backends.mps.is_available() if hasattr(torch.backends, 'mps') else False)"

# Reinstall if needed
pip install --upgrade torch
```

## Requirements

- Python 3.8 or later
- PyTorch 2.0 or later
- No platform-specific dependencies

## License

This is demonstration code for cross-platform PyTorch training.

## Contributing

When extending this code:
1. Test on multiple platforms (CUDA, MPS, CPU)
2. Avoid platform-specific imports or operations
3. Use device-agnostic PyTorch APIs
4. Add appropriate error handling and logging
