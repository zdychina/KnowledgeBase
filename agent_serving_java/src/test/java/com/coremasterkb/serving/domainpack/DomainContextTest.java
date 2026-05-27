package com.coremasterkb.serving.domainpack;

import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.util.concurrent.*;
import java.util.concurrent.atomic.AtomicReference;
import java.util.function.Supplier;

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

    // =========================================================================
    // wrapCallable / wrapRunnable / wrapSupplier propagation tests
    // =========================================================================

    @Test
    @DisplayName("wrapCallable propagates domain to child thread")
    void wrapCallable_propagatesDomain() throws Exception {
        DomainContext.set("cloud_core_network");

        Callable<String> task = DomainContext.wrapCallable(() -> DomainContext.get());

        AtomicReference<String> result = new AtomicReference<>();
        Thread t = new Thread(() -> {
            try { result.set(task.call()); } catch (Exception ignored) {}
        });
        t.start();
        t.join();

        assertThat(result.get()).isEqualTo("cloud_core_network");
    }

    @Test
    @DisplayName("wrapCallable clears domain after execution")
    void wrapCallable_clearsAfterExecution() throws Exception {
        DomainContext.set("cloud_core_network");

        Callable<Void> task = DomainContext.wrapCallable(() -> null);
        AtomicReference<String> afterRun = new AtomicReference<>();

        Thread t = new Thread(() -> {
            try { task.call(); } catch (Exception ignored) {}
            afterRun.set(DomainContext.get()); // should be null after cleanup
        });
        t.start();
        t.join();

        assertThat(afterRun.get()).isNull();
    }

    @Test
    @DisplayName("wrapRunnable propagates domain to child thread")
    void wrapRunnable_propagatesDomain() throws Exception {
        DomainContext.set("test_domain");

        AtomicReference<String> result = new AtomicReference<>();
        Runnable task = DomainContext.wrapRunnable(() -> result.set(DomainContext.get()));

        Thread t = new Thread(task);
        t.start();
        t.join();

        assertThat(result.get()).isEqualTo("test_domain");
    }

    @Test
    @DisplayName("wrapRunnable clears domain after execution")
    void wrapRunnable_clearsAfterExecution() throws Exception {
        DomainContext.set("test_domain");

        AtomicReference<String> afterRun = new AtomicReference<>();
        Runnable task = DomainContext.wrapRunnable(() -> {});

        Thread t = new Thread(() -> {
            task.run();
            afterRun.set(DomainContext.get());
        });
        t.start();
        t.join();

        assertThat(afterRun.get()).isNull();
    }

    @Test
    @DisplayName("wrapSupplier propagates domain to child thread")
    void wrapSupplier_propagatesDomain() throws Exception {
        DomainContext.set("supplier_domain");

        Supplier<String> task = DomainContext.wrapSupplier(DomainContext::get);

        AtomicReference<String> result = new AtomicReference<>();
        Thread t = new Thread(() -> result.set(task.get()));
        t.start();
        t.join();

        assertThat(result.get()).isEqualTo("supplier_domain");
    }

    @Test
    @DisplayName("wrapCallable works with CompletableFuture on virtual thread")
    void wrapCallable_completableFuture() throws Exception {
        DomainContext.set("cf_domain");

        ExecutorService executor = Executors.newVirtualThreadPerTaskExecutor();
        try {
            Future<String> future = executor.submit(
                    DomainContext.wrapCallable(() -> DomainContext.get()));
            assertThat(future.get(5, TimeUnit.SECONDS)).isEqualTo("cf_domain");
        } finally {
            executor.shutdown();
        }
    }

    @Test
    @DisplayName("wrapCallable captures null domain without error")
    void wrapCallable_nullDomain() throws Exception {
        // DomainContext not set — should be null
        assertThat(DomainContext.get()).isNull();

        Callable<String> task = DomainContext.wrapCallable(() -> DomainContext.get());

        AtomicReference<String> result = new AtomicReference<>();
        Thread t = new Thread(() -> {
            try { result.set(task.call()); } catch (Exception ignored) {}
        });
        t.start();
        t.join();

        assertThat(result.get()).isNull();
    }
}
