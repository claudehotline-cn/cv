## 深度学习基础：历史脉络与核心模型

深度学习的发展脉络始于1990年Elman网络，作为早期循环神经网络（RNN）代表用于序列建模，但梯度消失问题导致长序列信息丢失。1995年，长短期记忆（LSTM）网络提出，通过乘法单元和门控机制（输入门、遗忘门、输出门）有效解决梯度消失，成为长序列建模标准，直至2017年Transformer出现。2014年，序列到序列（seq2seq）架构基于双LSTM或GRU实现序列转换，但缺乏注意力机制，长输入导致信息压缩，输出质量下降。随后，RNN search模型引入注意力机制，动态关注输入序列关键token，提升长距离依赖建模能力，为Transformer奠定基础。

核心模型详解：
- **RNNs**：通过循环连接处理序列，每个时间步传递隐藏状态，但梯度消失限制长序列性能；LSTM（1995）和GRU（2014）优化了门控机制，计算效率更高。
- **CNNs**：专为网格数据（如图像）设计，卷积层提取局部特征（如边缘、纹理），池化层降维，AlexNet在2012年ImageNet竞赛中实现突破。
- **Transformer**：2017年Google论文《Attention Is All You Need》提出，基于多头注意力机制实现完全并行计算，训练时间比LSTM缩短40%以上，成为大型语言模型（GPT、BERT）和Vision Transformers（ViT）的基础。

关键对比：
- **RNNs vs Transformer**：RNNs顺序处理（时间复杂度O(n)），Transformer并行处理（O(n²)但实际加速），支持高效训练。
- **CNNs vs Transformer**：CNNs擅长局部特征提取（如图像边缘），Transformer处理全局依赖（如句子语义），融合应用如ViT在图像任务中超越传统CNN。
- **历史意义**：Transformer替代LSTM成为序列建模新标准，推动2020年GPT-3（1750亿参数）等LLMs的爆发式发展。