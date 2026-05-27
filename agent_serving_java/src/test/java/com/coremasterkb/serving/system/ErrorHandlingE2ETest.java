package com.coremasterkb.serving.system;

import com.coremasterkb.serving.AbstractPgIntegrationTest;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Tag;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc;
import org.springframework.http.MediaType;
import org.springframework.test.web.servlet.MockMvc;

import static org.assertj.core.api.Assertions.assertThat;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

@AutoConfigureMockMvc
@Tag("e2e")
@DisplayName("Error Handling E2E")
class ErrorHandlingE2ETest extends AbstractPgIntegrationTest {

    @Autowired
    private MockMvc mockMvc;

    @Test
    @DisplayName("nonexistent domain returns error status (4xx when registry loaded, 5xx otherwise)")
    void nonexistentDomainReturnsError() throws Exception {
        mockMvc.perform(post("/api/v1/search")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"query\":\"test\",\"domain\":\"nonexistent_domain\"}"))
                .andExpect(result -> assertThat(result.getResponse().getStatus()).isGreaterThanOrEqualTo(400));
    }

    @Test
    @DisplayName("blank query returns 400 query_required")
    void blankQueryReturns400() throws Exception {
        mockMvc.perform(post("/api/v1/search")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"query\":\"  \",\"domain\":\"cloud_core_network\"}"))
                .andExpect(status().isBadRequest())
                .andExpect(result -> assertThat(result.getResponse().getContentAsString())
                        .contains("query_required"));
    }

    @Test
    @DisplayName("missing query field returns 400 query_required")
    void missingQueryReturns400() throws Exception {
        mockMvc.perform(post("/api/v1/search")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"domain\":\"cloud_core_network\"}"))
                .andExpect(status().isBadRequest())
                .andExpect(result -> assertThat(result.getResponse().getContentAsString())
                        .contains("query_required"));
    }
}
