package com.coremasterkb.serving.domainpack;

import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.util.concurrent.atomic.AtomicReference;

import static org.assertj.core.api.Assertions.assertThat;

@DisplayName("DomainContext")
class DomainContextTest {

    @AfterEach
    void cleanup() {
        DomainContext.clear();
    }

    @Test
    @DisplayName("get returns null when not set")
    void nullByDefault() {
        assertThat(DomainContext.get()).isNull();
    }

    @Test
    @DisplayName("set and get round-trip")
    void setAndGet() {
        DomainContext.set("cloud_core_network");
        assertThat(DomainContext.get()).isEqualTo("cloud_core_network");
    }

    @Test
    @DisplayName("clear removes the value")
    void clearRemoves() {
        DomainContext.set("cloud_core_network");
        DomainContext.clear();
        assertThat(DomainContext.get()).isNull();
    }

    @Test
    @DisplayName("ThreadLocal isolation: other thread sees null")
    void threadLocalIsolation() throws InterruptedException {
        DomainContext.set("cloud_core_network");

        AtomicReference<String> otherThreadValue = new AtomicReference<>();
        Thread t = new Thread(() -> otherThreadValue.set(DomainContext.get()));
        t.start();
        t.join();

        assertThat(otherThreadValue.get()).isNull();
        assertThat(DomainContext.get()).isEqualTo("cloud_core_network");
    }
}
