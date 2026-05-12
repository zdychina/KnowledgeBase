package com.coremasterkb.serving.system;

import com.coremasterkb.serving.AbstractPgIntegrationTest;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Tag;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc;
import org.springframework.http.MediaType;
import org.springframework.test.web.servlet.MockMvc;

import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

@AutoConfigureMockMvc
@Tag("e2e")
@DisplayName("Error Handling E2E")
class ErrorHandlingE2ETest extends AbstractPgIntegrationTest {

    @Autowired
    private MockMvc mockMvc;

    @Test
    @DisplayName("nonexistent domain returns error status")
    void nonexistentDomainReturnsError() throws Exception {
        mockMvc.perform(post("/api/v1/search")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"query\":\"test\",\"domain\":\"nonexistent_domain\"}"))
                .andExpect(status().is5xxServerError());
    }
}
