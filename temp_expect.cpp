#ifdef _WIN32
                closesocket(client_socket);
#else
                close(client_socket);
#endif
                return;
            }
        }

        if (request.method == "OPTIONS") {
            HttpResponse response;
            response.status_code = 204;
            const auto raw = buildResponse(response);
            sendAll(client_socket, raw);
#ifdef _WIN32
            closesocket(client_socket);
#else
            close(client_socket);
#endif
            return;
        }

        size_t content_length = 0;
        bool has_content_length = false;
        bool expect_continue = false;
        for (const auto& entry : request.headers) {
            std::string header_name = toLower(entry.first);
            if (header_name == "content-length") {
                try {
                    content_length = static_cast<size_t>(std::stoll(entry.second));
                    has_content_length = true;
                } catch (...) {
                    content_length = 0;
                }
                continue;
            }
            if (header_name == "expect") {
                std::string v = toLower(entry.second);
                // Common pattern from clients like Postman when sending large bodies
                if (v.find("100-continue") != std::string::npos) expect_continue = true;
            }
        }

        if (has_content_length && request.body.size() < content_length) {
            if (expect_continue) {
                // Send 100-continue to prompt client to transmit the body
                const std::string cont = "HTTP/1.1 100 Continue\r\n\r\n";
                sendAll(client_socket, cont);
            }
            size_t remaining = content_length - request.body.size();
            while (remaining > 0) {
                const size_t chunk_size = (std::min)(remaining, static_cast<size_t>(buffer_size));
#ifdef _WIN32
                int read_bytes = recv(client_socket, buffer, static_cast<int>(chunk_size), 0);
#else
                int read_bytes = static_cast<int>(recv(client_socket, buffer, chunk_size, 0));
#endif
                if (read_bytes <= 0) {
                    break;
                }
                request.body.append(buffer, static_cast<size_t>(read_bytes));
