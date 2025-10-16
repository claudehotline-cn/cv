看起来你正在使用 `vcpkg` 构建 **libdatachannel**，并且在 `portfile.cmake` 中配置了构建选项。从这个文件来看，`libdatachannel` 是以默认配置进行构建的，并且通过 `NO_MEDIA` 禁用了媒体支持（如音视频轨道）。这就是为什么你遇到 **Track is closed** 错误的原因。

### 关键问题

在你的 `portfile.cmake` 文件中，有一个特别的地方：

```
vcpkg_check_features(OUT_FEATURE_OPTIONS FEATURE_OPTIONS
    FEATURES
        stdcall CAPI_STDCALL
    INVERTED_FEATURES
        ws      NO_WEBSOCKET
        srtp    NO_MEDIA
)
```

这里的 `NO_MEDIA` 表示**禁用了媒体支持**，所以 libdatachannel 无法处理视频轨道，导致发送视频流时出现 `Track is closed` 错误。

### 解决方案：启用媒体支持

要解决这个问题，你需要在构建时启用媒体支持。这可以通过修改 `portfile.cmake` 文件来实现，方法如下：

1. **修改 `portfile.cmake` 启用媒体支持**

   在你的 `portfile.cmake` 中找到 `NO_MEDIA` 这一行，并将其去掉。具体来说，修改部分如下：

   ```
   vcpkg_check_features(OUT_FEATURE_OPTIONS FEATURE_OPTIONS
       FEATURES
           stdcall CAPI_STDCALL
       INVERTED_FEATURES
           ws      NO_WEBSOCKET
       #    srtp    NO_MEDIA  # 移除这行
   )
   ```

2. **添加媒体支持选项**

   确保 libdatachannel 编译时启用了媒体支持，且你没有禁用它。可以直接在 `OPTIONS` 中添加或修改以下参数：

   ```
   vcpkg_cmake_configure(
       SOURCE_PATH "${SOURCE_PATH}"
       OPTIONS
           ${FEATURE_OPTIONS}
           -DPREFER_SYSTEM_LIB=ON
           -DNO_EXAMPLES=ON
           -DNO_TESTS=ON
           -DENABLE_MEDIA=ON  # 启用媒体支持
   )
   ```

3. **重新构建 libdatachannel**

   修改完 `portfile.cmake` 文件后，重新构建 libdatachannel：

   ```
   ./vcpkg install libdatachannel --recurse
   ```

4. **检查构建日志**

   在构建完成后，检查构建日志，确保没有禁用媒体支持，并且编译成功。