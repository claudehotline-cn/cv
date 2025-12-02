from typing import Any, Dict, Tuple
import os
import random
import torch
from torch.utils.data import DataLoader, Dataset


class RandomClsDataset(Dataset):
    def __init__(self, n: int, num_classes: int, size=(3, 224, 224)):
        self.n = n
        self.num_classes = num_classes
        self.size = size

    def __len__(self):
        return self.n

    def __getitem__(self, idx):
        x = torch.rand(*self.size)
        y = random.randrange(self.num_classes)
        return x, y


def build_imagefolder_loaders(root: str, batch_size: int) -> Tuple[DataLoader, int]:
    from torchvision import datasets, transforms
    tf = transforms.Compose([
        transforms.Resize((224, 224)),
        transforms.ToTensor(),
    ])
    ds = datasets.ImageFolder(root=root, transform=tf)
    num_classes = len(ds.classes) if hasattr(ds, 'classes') else 2
    loader = DataLoader(ds, batch_size=batch_size, shuffle=True, num_workers=0)
    return loader, num_classes


def build_dataloaders(cfg: Dict[str, Any]):
    dcfg = cfg.get('data', {})
    batch_size = int(cfg.get('train', {}).get('batch_size', 16))
    train_dir = dcfg.get('train_dir') or ''
    val_dir = dcfg.get('val_dir') or ''
    num_classes = int(dcfg.get('num_classes', 2))

    if train_dir and os.path.isdir(train_dir):
        train_loader, num_classes = build_imagefolder_loaders(train_dir, batch_size)
    else:
        train_loader = DataLoader(RandomClsDataset(64, num_classes), batch_size=batch_size, shuffle=True)

    if val_dir and os.path.isdir(val_dir):
        val_loader, _ = build_imagefolder_loaders(val_dir, batch_size)
    else:
        val_loader = DataLoader(RandomClsDataset(32, num_classes), batch_size=batch_size, shuffle=False)

    return train_loader, val_loader, num_classes

