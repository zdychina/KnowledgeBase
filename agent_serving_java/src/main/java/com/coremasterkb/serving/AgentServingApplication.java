package com.coremasterkb.serving;

import org.mybatis.spring.annotation.MapperScan;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.boot.context.properties.EnableConfigurationProperties;

import com.coremasterkb.serving.config.ServingProperties;

@SpringBootApplication
@EnableConfigurationProperties(ServingProperties.class)
@MapperScan("com.coremasterkb.serving.mapper")
public class AgentServingApplication {

    public static void main(String[] args) {
        SpringApplication.run(AgentServingApplication.class, args);
    }
}