-- public.asset_build_document_snapshots definition

-- Drop table

-- DROP TABLE public.asset_build_document_snapshots;

CREATE TABLE public.asset_build_document_snapshots (
                                                       build_id text NOT NULL,
                                                       document_id text NOT NULL,
                                                       document_snapshot_id text NOT NULL,
                                                       selection_status text NOT NULL,
                                                       reason text NOT NULL,
                                                       metadata_json text NOT NULL
);


-- public.asset_builds definition

-- Drop table

-- DROP TABLE public.asset_builds;

CREATE TABLE public.asset_builds (
                                     id text NULL,
                                     build_code text NOT NULL,
                                     status text NOT NULL,
                                     build_mode text NOT NULL,
                                     source_batch_id text NULL,
                                     parent_build_id text NULL,
                                     mining_run_id text NULL,
                                     summary_json text NOT NULL,
                                     validation_json text NOT NULL,
                                     created_at text NOT NULL,
                                     finished_at text NULL
);


-- public.asset_document_snapshot_links definition

-- Drop table

-- DROP TABLE public.asset_document_snapshot_links;

CREATE TABLE public.asset_document_snapshot_links (
                                                      id text NULL,
                                                      document_id text NOT NULL,
                                                      document_snapshot_id text NOT NULL,
                                                      source_batch_id text NULL,
                                                      relative_path text NOT NULL,
                                                      source_uri text NOT NULL,
                                                      title text NULL,
                                                      scope_json text NOT NULL,
                                                      tags_json text NOT NULL,
                                                      linked_at text NOT NULL,
                                                      metadata_json text NOT NULL
);


-- public.asset_document_snapshots definition

-- Drop table

-- DROP TABLE public.asset_document_snapshots;

CREATE TABLE public.asset_document_snapshots (
                                                 id text NULL,
                                                 normalized_content_hash text NOT NULL,
                                                 raw_content_hash text NOT NULL,
                                                 mime_type text NOT NULL,
                                                 title text NULL,
                                                 scope_json text NOT NULL,
                                                 tags_json text NOT NULL,
                                                 parser_profile_json text NOT NULL,
                                                 metadata_json text NOT NULL,
                                                 created_at text NOT NULL
);


-- public.asset_documents definition

-- Drop table

-- DROP TABLE public.asset_documents;

CREATE TABLE public.asset_documents (
                                        id text NULL,
                                        document_key text NOT NULL,
                                        document_name text NULL,
                                        document_type text NULL,
                                        metadata_json text NOT NULL,
                                        created_at text NOT NULL
);


-- public.asset_publish_releases definition

-- Drop table

-- DROP TABLE public.asset_publish_releases;

CREATE TABLE public.asset_publish_releases (
                                               id text NULL,
                                               release_code text NOT NULL,
                                               build_id text NOT NULL,
                                               channel text NOT NULL,
                                               status text NOT NULL,
                                               previous_release_id text NULL,
                                               released_by text NULL,
                                               release_notes text NULL,
                                               activated_at text NULL,
                                               deactivated_at text NULL,
                                               metadata_json text NOT NULL
);


-- public.asset_raw_segment_relations definition

-- Drop table

-- DROP TABLE public.asset_raw_segment_relations;

CREATE TABLE public.asset_raw_segment_relations (
                                                    id text NULL,
                                                    document_snapshot_id text NOT NULL,
                                                    source_segment_id text NOT NULL,
                                                    target_segment_id text NOT NULL,
                                                    relation_type text NOT NULL,
                                                    weight float4 NOT NULL,
                                                    confidence float4 NOT NULL,
                                                    distance int4 NULL,
                                                    metadata_json text NOT NULL
);


-- public.asset_raw_segments definition

-- Drop table

-- DROP TABLE public.asset_raw_segments;

CREATE TABLE public.asset_raw_segments (
                                           id text NULL,
                                           document_snapshot_id text NOT NULL,
                                           segment_key text NOT NULL,
                                           segment_index int4 NOT NULL,
                                           section_path text NOT NULL,
                                           section_title text NULL,
                                           block_type text NOT NULL,
                                           semantic_role text NOT NULL,
                                           raw_text text NOT NULL,
                                           normalized_text text NOT NULL,
                                           content_hash text NOT NULL,
                                           normalized_hash text NOT NULL,
                                           token_count int4 NULL,
                                           structure_json text NOT NULL,
                                           source_offsets_json text NOT NULL,
                                           entity_refs_json text NOT NULL,
                                           metadata_json text NOT NULL
);


-- public.asset_retrieval_embeddings definition

-- Drop table

-- DROP TABLE public.asset_retrieval_embeddings;

CREATE TABLE public.asset_retrieval_embeddings (
                                                   id text NULL,
                                                   retrieval_unit_id text NOT NULL,
                                                   embedding_model text NOT NULL,
                                                   embedding_provider text NOT NULL,
                                                   text_kind text NOT NULL,
                                                   embedding_dim int4 NOT NULL,
                                                   embedding_vector text NOT NULL,
                                                   content_hash text NOT NULL,
                                                   created_at text NOT NULL,
                                                   metadata_json text NOT NULL
);


-- public.asset_retrieval_units definition

-- Drop table

-- DROP TABLE public.asset_retrieval_units;

CREATE TABLE public.asset_retrieval_units (
                                              id text NULL,
                                              document_snapshot_id text NOT NULL,
                                              unit_key text NOT NULL,
                                              unit_type text NOT NULL,
                                              target_type text NOT NULL,
                                              target_ref_json text NOT NULL,
                                              title text NULL,
                                              "text" text NOT NULL,
                                              search_text text NOT NULL,
                                              block_type text NOT NULL,
                                              semantic_role text NOT NULL,
                                              facets_json text NOT NULL,
                                              entity_refs_json text NOT NULL,
                                              source_refs_json text NOT NULL,
                                              llm_result_refs_json text NOT NULL,
                                              source_segment_id text NULL,
                                              weight float4 NOT NULL,
                                              created_at text NOT NULL,
                                              metadata_json text NOT NULL
);


-- public.asset_source_batches definition

-- Drop table

-- DROP TABLE public.asset_source_batches;

CREATE TABLE public.asset_source_batches (
                                             id text NULL,
                                             batch_code text NOT NULL,
                                             source_type text NOT NULL,
                                             description text NULL,
                                             created_by text NULL,
                                             created_at text NOT NULL,
                                             metadata_json text NOT NULL
);