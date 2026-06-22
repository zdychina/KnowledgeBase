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
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

@AutoConfigureMockMvc
@Tag("e2e")
@DisplayName("Search E2E")
class SearchE2ETest extends AbstractPgIntegrationTest {

    @Autowired
    private MockMvc mockMvc;

    @Test
    @DisplayName("query returns valid ContextPack structure")
    void queryReturnsValidContextPack() throws Exception {
        mockMvc.perform(post("/api/v1/search")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"query\":\"Test Document\",\"domain\":\"cloud_core_network\"}"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.query").exists())
                .andExpect(jsonPath("$.query.original").value("Test Document"));
    }

    @Test
    @DisplayName("'ADD SMFPARTNER 命令怎么写' detects command_usage intent")
    void commandUsageIntent() throws Exception {
        mockMvc.perform(post("/api/v1/search")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"query\":\"ADD SMFPARTNER 命令怎么写\",\"domain\":\"cloud_core_network\"}"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.query.intent").value("command_usage"));
    }

    @Test
    @DisplayName("'UDG和UNC的区别' detects comparison intent")
    void comparisonIntent() throws Exception {
        mockMvc.perform(post("/api/v1/search")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"query\":\"UDG和UNC的区别\",\"domain\":\"cloud_core_network\"}"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.query.intent").value("comparison"));
    }

    @Test
    @DisplayName("'你好' detects general intent")
    void generalIntent() throws Exception {
        mockMvc.perform(post("/api/v1/search")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"query\":\"你好\",\"domain\":\"cloud_core_network\"}"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.query.intent").value("general"));
    }
}
