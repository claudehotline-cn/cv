package com.cv.cp.config;

import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.security.config.Customizer;
import org.springframework.security.config.annotation.web.builders.HttpSecurity;
import org.springframework.security.config.annotation.web.configuration.EnableWebSecurity;
import org.springframework.security.web.SecurityFilterChain;

@Configuration
@EnableWebSecurity
public class SecurityConfig {

  private final AppProperties appProperties;

  public SecurityConfig(AppProperties appProperties) {
    this.appProperties = appProperties;
  }

  @Bean
  public SecurityFilterChain securityFilterChain(HttpSecurity http) throws Exception {
    http
        .csrf(csrf -> csrf.disable())
        .authorizeHttpRequests(auth -> {
          // 若未配置 bearer token，则保持与当前行为一致：全部放行
          String token = appProperties.getSecurity() != null
              ? appProperties.getSecurity().getAuth() != null
                  ? appProperties.getSecurity().getAuth().getBearerToken()
                  : null
              : null;
          if (token == null || token.isEmpty()) {
            auth.anyRequest().permitAll();
          } else {
            auth.requestMatchers(
                    "/actuator/**",
                    "/api/system/info",
                    "/api/va/runtime",
                    "/api/sources",
                    "/api/sources/watch_sse")
                .permitAll()
                .anyRequest().authenticated();
          }
        });
    String token = appProperties.getSecurity() != null
        ? appProperties.getSecurity().getAuth() != null
            ? appProperties.getSecurity().getAuth().getBearerToken()
            : null
        : null;
    if (token != null && !token.isEmpty()) {
      http.addFilterBefore(new BearerTokenFilter(token),
          org.springframework.security.web.authentication.UsernamePasswordAuthenticationFilter.class);
    }
    http.httpBasic(Customizer.withDefaults())
        .formLogin(form -> form.disable());
    return http.build();
  }
}
