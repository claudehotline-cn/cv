## Transformer的起源：突破序列模型的局限

Transformer的诞生源于对序列模型局限性的深刻反思。传统RNN/LSTM虽能处理长序列，但因**顺序计算**导致效率低下，且难以捕捉全局依赖（如seq2seq模型在翻译任务中因信息丢失表现不佳）。2017年，Google团队在《Attention Is All You Need》中提出**完全基于注意力机制**的Transformer架构，彻底摒弃循环结构，实现并行计算。

### 核心创新
- **多头注意力机制**：通过Query-Key-Value动态加权，实现全局上下文建模（图1：位置编码的正弦函数可视化）。
- **位置编码**：使用正弦/余弦函数注入位置信息，解决序列顺序丢失问题。
- **前馈网络**：独立处理每个token，增强表达能力。

### 技术演进与影响
Transformer的并行化使训练效率提升数倍，推动大规模预训练模型（如BERT、GPT）的发展。在图像处理领域，**Vision Transformer（ViT）**通过分块处理图像，与CNN对比实验显示其在ImageNet分类任务中达到SOTA性能（如Top-1准确率超越ResNet-50）。这一突破证明了Transformer的通用性，使其从NLP扩展至计算机视觉、音频处理等领域。

> **关键里程碑**：Vaswani等人（2017）提出Transformer，Dosovitskiy等人（2020）将Transformer引入视觉任务，标志着序列模型范式的彻底革新。