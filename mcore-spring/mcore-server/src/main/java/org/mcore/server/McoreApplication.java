package org.mcore.server;

import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.context.annotation.ComponentScan;

@SpringBootApplication
@ComponentScan(basePackages = "org.mcore")
public class McoreApplication {
    public static void main(String[] args) {
        SpringApplication.run(McoreApplication.class, args);
    }
}
