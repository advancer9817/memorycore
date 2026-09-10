package org.mcore.server;

import org.mybatis.spring.annotation.MapperScan;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.context.annotation.ComponentScan;

@SpringBootApplication
@ComponentScan(basePackages = "org.mcore")
@MapperScan("org.mcore.storage.mapper")
public class McoreApplication {
    public static void main(String[] args) {
        SpringApplication.run(McoreApplication.class, args);
    }
}
