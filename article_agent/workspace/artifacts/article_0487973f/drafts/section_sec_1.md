## 引言：深度学习与Transformer的革命性影响  
深度学习通过多层神经网络实现特征分层抽象，其核心在于**自监督学习**与**端到端优化**。以图像识别为例，输入层提取像素信息，经多层卷积后逐步形成从边缘到物体的抽象表示（如图1所示）。然而，传统RNN因梯度消失问题难以处理长序列依赖，直到2017年Transformer架构的提出，彻底改变了序列建模范式。  

### Transformer架构与技术突破  
Transformer通过**自注意力机制**（Self-Attention）实现并行计算，其核心公式为：  
$$
\text{Attention}(Q, K, V) = \text{softmax}\left(\frac{QK^T}{\sqrt{d_k}}\right)V
$$  
其中，$ Q, K, V $ 分别为查询、键、值矩阵，$ d_k $ 为键向量维度。多头注意力机制通过并行计算多个注意力头，增强模型对不同语义关系的捕捉能力（如图2所示）。  

### ViT在计算机视觉中的应用  
视觉Transformer（ViT）将图像分割为固定大小的patch，输入Transformer编码器。在ImageNet-1K数据集上，ViT-Base模型达到**84.2%的Top-1准确率**，超越ResNet-50（76.5%）和EfficientNet-B3（82.1%），验证了Transformer在视觉任务中的有效性（表1）。  

| 模型         | 参数量（M） | ImageNet-1K准确率（Top-1） |  
|--------------|-------------|-----------------------------|  
| ResNet-50    | 25.6        | 76.5                      |  
| EfficientNet-B3 | 14.3      | 82.1                      |  
| ViT-Base     | 86.8        | **84.2**                  |  

Transformer的并行计算优势与长距离依赖建模能力，使其成为NLP、CV等领域的通用架构，推动了大规模语言模型（如GPT-3）与多模态系统（如CLIP）的突破性发展。