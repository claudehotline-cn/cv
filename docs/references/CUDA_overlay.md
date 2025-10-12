明白，你是“后端 CUDA 画框”。你现在看到的“全灰色框”，**99% 是只改了 NV12 的 Y 平面、没改 UV 平面**（U/V 留在 128 → 无色），或者在 4:2:0 下写 UV 的方式不对（没按 2×2 采样对齐/平均）。下面给你一套 **CUDA 上的 OSD 最佳实践**，含可直接用的内核骨架（NV12 & RGBA 路径都有），保证“好看 + 不灰 + 高性能”。

------

# 关键原则（CUDA / NV12）

1. **NV12 必须同时写 Y 与 UV**

- NV12 = Y (W×H) + 交错 UV (W×H/2)，每个 UV 采样对应 **2×2** 像素块。
- 覆盖时：Y 按像素混合；UV 要对这 2×2 内四个像素的“覆盖度 α”做**平均**后再混合。

1. **抗锯齿 & 圆角**

- 用“**有符号距离函数 (SDF)**”对圆角矩形做边缘平滑（`smoothstep`），边框粗细、填充、halo 都好做。
- 公式见内核骨架（基于 Inigo Quilez 的 rounded-rect SDF）。

1. **颜色空间**

- 若直接在 NV12 里绘制，先把期望的 sRGB 颜色换算到 **BT.709 限幅 YUV**（Y∈[16,235], U/V∈[16,240]）。
- HDR(P010/2020/PQ) 时建议换算到 **BT.2020 限幅**，并控制饱和度避免 OOTF/tonemap 后“荧光色”。

1. **性能**

- **Tile + Binning**：将框按 32×32 或 64×64 tile 预分桶；一个 CUDA block 画一个 tile 只遍历相关框，成百上千框也稳。
- **两遍法**：第一遍写 Y（逐像素 SDF），第二遍每 2×2 写一次 UV（聚合四个 α）。
- pitch/stride：NVDEC/NVENC 的 pitch 常大于 width，**所有寻址用 pitch**。
- 批量：把类别调色板放 `__constant__`，框参数放全局内存，尽量少分支。

------

# 可用色板 & 颜色稳定策略

- Okabe–Ito 扩展（色弱友好）：`#0072B2,#E69F00,#F0E442,#009E73,#56B4E9,#D55E00,#CC79A7,#999999,#0091D5,#6C8EBF`
- 颜色 = `palette[hash(cls)%N]`，若有 track id，再微调色相（±12°）。
- 把 hex 转 sRGB→BT.709 限幅 YUV，缓存到框结构体里，避免每像素色彩矩阵乘法。

------

# CUDA 内核骨架（NV12，AA 圆角框 + 填充 + 边框）

> 说明：给出“**两遍法**”的核心。你只要把检测框列表填好（像素坐标），把表面指针（Y/UV）+ pitch 传进来即可。

```
struct Box {
    float x, y, w, h;   // 像素坐标
    float radius;       // 圆角半径
    float stroke;       // 描边粗细(px)
    float fillAlpha;    // 填充透明度(0~1)
    float strokeAlpha;  // 描边透明度(0~1)
    unsigned char Yc, Uc, Vc; // 目标颜色(限幅709)
};

__device__ __forceinline__ float sdRoundRect(float2 p, float2 b, float r){
    // p: 相对中心坐标; b: 半宽半高; r: 圆角
    float2 q = make_float2(fabsf(p.x) - b.x + r, fabsf(p.y) - b.y + r);
    float outside = hypotf(fmaxf(q.x,0.f), fmaxf(q.y,0.f)) - r;
    float inside  = fminf(fmaxf(q.x, q.y), 0.f);
    return outside + inside; // <0 inside; ~=0 边缘; >0 outside
}

// --- Pass 1: Y 平面 --- //
extern "C" __global__
void draw_boxes_Y(
    unsigned char* __restrict__ Y, int width, int height, int pitchY,
    const Box* __restrict__ boxes, int nBoxes)
{
    int x = blockIdx.x * blockDim.x + threadIdx.x; // 像素坐标
    int y = blockIdx.y * blockDim.y + threadIdx.y;
    if (x >= width || y >= height) return;

    // 读取原 Y
    unsigned char* row = Y + y * pitchY;
    float Ydst = (float)row[x];

    // 遍历相关框（生产中用 tile-binning 减少遍历）
    float accumA = 0.f, accumY = 0.f; // Porter-Duff over
    for (int i = 0; i < nBoxes; ++i) {
        const Box& b = boxes[i];
        // 快速剔除：在外扩 stroke+1 的 AABB 之外直接跳过
        if (x < b.x - b.stroke - 2 || x > b.x + b.w + b.stroke + 2 ||
            y < b.y - b.stroke - 2 || y > b.y + b.h + b.stroke + 2) continue;

        // SDF
        float2 c = make_float2(b.x + b.w * 0.5f, b.y + b.h * 0.5f);
        float2 p = make_float2(x - c.x, y - c.y);
        float2 half = make_float2(b.w * 0.5f, b.h * 0.5f);

        float d = sdRoundRect(p, half, b.radius);

        // 填充 coverage
        float aFill = 0.f;
        if (b.fillAlpha > 0.f) {
            // 负距内部，边缘 1px 做平滑（AA）
            float t = -d; // inside positive
            aFill = __saturatef(t + 0.5f); // 约等 smoothstep(-0.5,0.5,-d)
            aFill *= b.fillAlpha;
        }

        // 描边 coverage
        float aStroke = 0.f;
        if (b.stroke > 0.f && b.strokeAlpha > 0.f) {
            float ad = fabsf(d);
            // 让 ad 在 [S-0.5, S+0.5] 过渡
            float edge = fabsf(ad - b.stroke * 0.5f);
            float aa = 1.f - __saturatef(edge - 0.5f); // ~smoothstep
            // 只在“环带”范围内保留
            float ring = __saturatef((b.stroke * 0.5f + 0.5f) - ad) *
                         __saturatef(ad - (b.stroke * 0.5f - 0.5f));
            aStroke = aa * ring * b.strokeAlpha;
        }

        float a = fminf(1.f, aFill + aStroke); // 合并覆盖度

        if (a > 0.f) {
            // Porter-Duff over (线性域近似)
            float src = (float)b.Yc;
            accumY = src * a + accumY * (1.f - a);
            accumA = a + accumA * (1.f - a);
        }
    }

    if (accumA > 0.f) {
        // 与原像素再做一次 over（可选：直接写 accumY 也行）
        float outY = accumY + Ydst * (1.f - accumA);
        row[x] = (unsigned char)(fminf(235.f, fmaxf(16.f, outY)));
    }
}

// --- Pass 2: UV 平面（2x2 聚合） --- //
extern "C" __global__
void draw_boxes_UV(
    unsigned char* __restrict__ Y,  int width, int height, int pitchY,
    unsigned char* __restrict__ UV, int pitchUV,
    const Box* __restrict__ boxes, int nBoxes)
{
    int ux = blockIdx.x * blockDim.x + threadIdx.x; // UV 像素坐标（与 Y 同宽/高的一半）
    int uy = blockIdx.y * blockDim.y + threadIdx.y;
    if (ux >= (width/2) || uy >= (height/2)) return;

    // 2x2 对应的 Y 起点
    int x0 = ux * 2, y0 = uy * 2;

    // 计算这 2x2 的平均覆盖与期望 U/V
    float accumU = 0.f, accumV = 0.f, accumA = 0.f;

    // 对 2x2 的四个像素复算 α（与 Y pass 同样 SDF，省显存；若已缓存 α，可直接读）
    for (int oy = 0; oy < 2; ++oy)
    for (int ox = 0; ox < 2; ++ox) {
        int x = x0 + ox, y = y0 + oy;
        float aPix = 0.f;
        for (int i = 0; i < nBoxes; ++i) {
            const Box& b = boxes[i];
            if (x < b.x - b.stroke - 2 || x > b.x + b.w + b.stroke + 2 ||
                y < b.y - b.stroke - 2 || y > b.y + b.h + b.stroke + 2) continue;

            float2 c = make_float2(b.x + b.w * 0.5f, b.y + b.h * 0.5f);
            float2 p = make_float2(x - c.x, y - c.y);
            float2 half = make_float2(b.w * 0.5f, b.h * 0.5f);
            float d = sdRoundRect(p, half, b.radius);

            float aFill = 0.f, aStroke = 0.f;
            if (b.fillAlpha > 0.f) {
                float t = -d; aFill = __saturatef(t + 0.5f) * b.fillAlpha;
            }
            if (b.stroke > 0.f && b.strokeAlpha > 0.f) {
                float ad = fabsf(d);
                float edge = fabsf(ad - b.stroke * 0.5f);
                float aa = 1.f - __saturatef(edge - 0.5f);
                float ring = __saturatef((b.stroke*0.5f+0.5f)-ad) *
                             __saturatef(ad-(b.stroke*0.5f-0.5f));
                aStroke = aa * ring * b.strokeAlpha;
            }
            float a = fminf(1.f, aFill + aStroke);
            // 累加方式：取最大 a 对应的 U/V（也可做加权平均，这里简化）
            if (a > aPix) aPix = a;
        }
        // 将该像素 aPix 贡献进 2x2
        if (aPix > 0.f) {
            // 简化：使用最近一次命中的框颜色。生产可在上一循环记录对应 Uc/Vc。
            // 这里演示：用第一个命中的框色（再循环一遍找色）
            for (int i = 0; i < nBoxes; ++i) {
                const Box& b = boxes[i];
                if (x < b.x - b.stroke - 2 || x > b.x + b.w + b.stroke + 2 ||
                    y < b.y - b.stroke - 2 || y > b.y + b.h + b.stroke + 2) continue;
                float2 c = make_float2(b.x + b.w * 0.5f, b.y + b.h * 0.5f);
                float2 p = make_float2(x - c.x, y - c.y);
                float2 half = make_float2(b.w*0.5f, b.h*0.5f);
                float d = sdRoundRect(p, half, b.radius);
                float t = -d;
                float aFill = __saturatef(t + 0.5f) * b.fillAlpha;
                float ad = fabsf(d);
                float edge = fabsf(ad - b.stroke*0.5f);
                float aa = 1.f - __saturatef(edge - 0.5f);
                float ring = __saturatef((b.stroke*0.5f+0.5f)-ad) *
                             __saturatef(ad-(b.stroke*0.5f-0.5f));
                float aStroke = aa * ring * b.strokeAlpha;
                float a = fminf(1.f, aFill + aStroke);
                if (a > 0.f) { accumU += a * b.Uc; accumV += a * b.Vc; accumA += a; break; }
            }
        }
    }

    unsigned char* uvRow = UV + uy * pitchUV;
    unsigned char  U0 = uvRow[ux*2 + 0];
    unsigned char  V0 = uvRow[ux*2 + 1];

    if (accumA > 0.f) {
        float a = fminf(1.f, accumA / 4.f); // 4 像素平均
        float Usrc = accumU / accumA;
        float Vsrc = accumV / accumA;
        float Uout = Usrc * a + U0 * (1.f - a);
        float Vout = Vsrc * a + V0 * (1.f - a);
        uvRow[ux*2 + 0] = (unsigned char)(fminf(240.f, fmaxf(16.f, Uout)));
        uvRow[ux*2 + 1] = (unsigned char)(fminf(240.f, fmaxf(16.f, Vout)));
    }
}
```

**网格/启动方式（示例）**

```
dim3 blk(32, 8);
dim3 grdY( (W+blk.x-1)/blk.x, (H+blk.y-1)/blk.y );
draw_boxes_Y<<<grdY, blk>>>(Y, W, H, pitchY, d_boxes, n);

dim3 grdUV( ((W/2)+blk.x-1)/blk.x, ((H/2)+blk.y-1)/blk.y );
draw_boxes_UV<<<grdUV, blk>>>(Y, W, H, pitchY, UV, pitchUV, d_boxes, n);
```

> ⚠️ 实战请加 **tile-binning**：CPU 端把每个 tile 的候选框索引写到紧凑列表（或用 CUB/Thrust 做并行 compaction），内核只遍历该 tile 的少量框，复杂度从 O(W×H×N) → O(W×H×k)。

------

# 颜色转换（sRGB → BT.709 限幅 YUV）

```
// sRGB 0~1 -> 线性，再用 BT.709 矩阵
static inline float srgb_to_lin(float c){
    return c<=0.04045f ? c/12.92f : powf((c+0.055f)/1.055f, 2.4f);
}
static inline void rgb_to_yuv709_limited(float R8,float G8,float B8,
                                         unsigned char& Yc, unsigned char& Uc, unsigned char& Vc) {
    float R = srgb_to_lin(R8/255.f);
    float G = srgb_to_lin(G8/255.f);
    float B = srgb_to_lin(B8/255.f);
    // BT.709 (参考)
    float Y  = 0.2126f*R + 0.7152f*G + 0.0722f*B;
    float Cb = (B - Y) / 1.8556f;   // 0.5*(B-Y)/(1-0.114)
    float Cr = (R - Y) / 1.5748f;   // 0.5*(R-Y)/(1-0.299)
    // 限幅映射
    float Yl = 16.f  + 219.f * Y;
    float Ul = 128.f + 224.f * Cb;
    float Vl = 128.f + 224.f * Cr;
    Yc = (unsigned char)fminf(235.f, fmaxf(16.f,  Yl));
    Uc = (unsigned char)fminf(240.f, fmaxf(16.f,  Ul));
    Vc = (unsigned char)fminf(240.f, fmaxf(16.f,  Vl));
}
```

------

# RGBA 路径（如果你的管线中本来就有 RGBA）

- 在 RGBA 做 SDF 画框（单遍就行，直接 alpha blend），**再**做一次 `cvtColorRGBA2NV12`（NPP/CV-CUDA）。
- 优点：实现简单、文本渲染容易；缺点：一次 RGB↔YUV 转换开销。
- 内核同理，只是把 Y/UV 混合替换成 RGBA 的 `over()`。

------

# 文本与标签（CUDA 端）

1. **标签药丸**：用同一套 SDF 圆角矩形画底（半透明深色 + 微光晕），**再**把文字叠上去。
2. **文字建议用 SDF 字形图集**：
   - 启动时用 FreeType/msdfgen 在 CPU 端生成 glyph SDF/MSDF atlas + 每字形的 UV/advance，上传到 GPU 常驻。
   - 文字渲染内核：对每个像素从 atlas 采样 alpha，`over()` 到 NV12（同样两遍法：Y 像素，UV 聚合）。
   - 小框阈值：当框面积 < 全帧 0.3% 时，只画边框不绘字，避免噪点。

> 不想自己写字：DeepStream 的 **NvOSD** 直接在 GPU 上画框/文本（Pango 字体），用 GStreamer/DS 管线非常省心。

------

# 视觉“质感”参数（和前端版保持一致）

- **圆角**：`r = min(w,h) * 0.06`
- **描边**：`stroke = 2.0~3.0 px`（置信度越高越粗，1.5~3.5 动态）
- **填充透明度**：`0.08~0.16`（置信度调制）
- **Halo**：画一个“加粗 1px 的外描边 + 低 α”（可用 SDF 的 d 向外偏移实现）
- **标签位置**：优先框外上方，越界就放下方；小框仅类目，不显示置信度/ID。

------

# 常见坑位速查

- **灰框**：只改了 Y，没改 UV；或 UV 没按 2×2 聚合 → 改用上面“第二遍 UV”的逻辑。
- **颜色寡淡**：用的是全幅 YUV 或 sRGB 直接塞进 NV12 → 用 **BT.709 限幅**转换。
- **边缘锯齿**：没有 SDF/AA，或者在 NV12 只做 Y 的 AA → 记得 UV 也做 2×2 平滑聚合。
- **Pitch 问题**：`pitch != width` 被忽略 → 所有寻址用 `pitchY/pitchUV`。
- **HDR 偏色**：BT.2020/PQ 视频里按 709 混合 → 换 2020 矩阵/限幅，颜色别太纯。