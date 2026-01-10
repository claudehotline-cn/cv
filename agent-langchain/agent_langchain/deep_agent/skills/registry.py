"""
Skills Registry for Analyst Agent.
Stores the prompts and examples for different analysis skills.
"""

SKILLS_REGISTRY = {
    "general": {
        "name": "General Data Processing",
        "instruction": """
[Step 3.1] 数据清洗
- 类型转换
- 缺失值处理
- 排序

[Step 3.2] 核心变换
场景 A (绘图准备): 许多图表需要宽表，请使用 pivot_table
场景 B (聚合计算): groupby sum/mean/count
""",
        "examples": """
# 示例：一般数据处理
# result = df.groupby('month')['total_amount'].sum()
"""
    },
    "statistics": {
        "name": "Statistical Analysis (scipy/statsmodels)",
        "instruction": """
**【核心能力】**
1. **描述性统计**：均值、标准差、分位数、偏度、峰度
2. **假设检验**：t检验、卡方检验、ANOVA、Mann-Whitney U
3. **相关性分析**：Pearson、Spearman
4. **回归分析**：线性回归

**必须输出**：
- 统计量值（t-stat, F-stat, chi2）
- p-value
- 效应量
- 自然语言解释结论
        """,
        "examples": """
# 示例：T检验
# from scipy import stats
# group_a = df[df['group']=='A']['value']
# group_b = df[df['group']=='B']['value']
# t_stat, p_val = stats.ttest_ind(group_a, group_b)
# print(f"T-test result: t={t_stat}, p={p_val}")
"""
    },
    "ml": {
        "name": "Machine Learning (scikit-learn)",
        "instruction": """
**【核心能力】**
1. **数据预处理**：StandardScaler, LabelEncoder, SimpleImputer
2. **特征工程**：PCA, SelectKBest
3. **聚类分析**：K-Means, DBSCAN
4. **异常检测**：Isolation Forest
5. **分类/回归**（用于预测）

**【禁止事项】**
- ❌ 禁止保存模型到文件
- ❌ 禁止使用 pickle
        """,
        "examples": """
# 示例：K-Means 聚类
# from sklearn.cluster import KMeans
# from sklearn.preprocessing import StandardScaler
# X = df[['col1', 'col2']]
# X_scaled = StandardScaler().fit_transform(X)
# kmeans = KMeans(n_clusters=3).fit(X_scaled)
# df['cluster'] = kmeans.labels_
# result = df
"""
    }
}
