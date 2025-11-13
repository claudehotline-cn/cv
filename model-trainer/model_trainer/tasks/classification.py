from typing import Any, Dict
import torch
import torch.nn as nn
import torch.optim as optim


def build_model(cfg: Dict[str, Any], num_classes: int):
    arch = cfg.get('model', {}).get('arch', 'resnet18')
    pretrained = bool(cfg.get('model', {}).get('pretrained', True))
    from torchvision import models
    if arch == 'resnet18':
        m = models.resnet18(weights=models.ResNet18_Weights.DEFAULT if pretrained else None)
        m.fc = nn.Linear(m.fc.in_features, num_classes)
    else:
        # fallback to resnet18
        m = models.resnet18(weights=models.ResNet18_Weights.DEFAULT if pretrained else None)
        m.fc = nn.Linear(m.fc.in_features, num_classes)
    return m


def train_one_experiment(model: nn.Module, train_loader, val_loader, cfg: Dict[str, Any], device: str = 'cpu'):
    epochs = int(cfg.get('train', {}).get('epochs', 5))
    lr = float(cfg.get('train', {}).get('lr', 1e-3))
    model.to(device)
    criterion = nn.CrossEntropyLoss()
    optimizer = optim.AdamW(model.parameters(), lr=lr)
    model.train()
    for ep in range(epochs):
        total = 0
        correct = 0
        loss_sum = 0.0
        for x, y in train_loader:
            x = x.to(device)
            y = y.to(device)
            optimizer.zero_grad()
            logits = model(x)
            loss = criterion(logits, y)
            loss.backward()
            optimizer.step()
            loss_sum += float(loss.detach().cpu())
            pred = logits.argmax(dim=1)
            total += y.size(0)
            correct += (pred == y).sum().item()
        train_acc = correct / max(1, total)
        train_loss = loss_sum / max(1, len(train_loader))
        # could print progress as JSON if needed
    return True


@torch.no_grad()
def evaluate(model: nn.Module, val_loader, device: str = 'cpu'):
    model.eval()
    total = 0
    correct = 0
    for x, y in val_loader:
        x = x.to(device)
        y = y.to(device)
        logits = model(x)
        pred = logits.argmax(dim=1)
        total += y.size(0)
        correct += (pred == y).sum().item()
    acc = correct / max(1, total)
    return {"val/accuracy": acc}

