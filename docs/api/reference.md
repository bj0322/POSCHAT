# API 레퍼런스 (1.10)

## 1. Bridge (JS → Python, `window.pywebview.api.<메서드>`)
`workspace_api.WorkspaceApi`(main.Bridge가 상속). 비밀 값은 돌려주지 않는다.

| 영역 | 메서드 |
|---|---|
| 기능 플래그 | `get_features()`, `set_feature(name, enabled)` — `connectors, research, memory_hub, sync, automation, observability` |
| 커넥터 | `get_connectors()`, `set_connector_enabled(id, on)`, `set_connector_secret(id, field, value)`, `set_connector_option(id, name, value)`, `set_connector_policy(id, tool, ""|allow|ask|deny)`, `set_server_policy(server, ""|ask_all)`, `set_oauth_client(provider, client_id, secret, clear)`, `connector_login(id)`, `connector_cancel_login(id)`, `connector_logout(id)`, `connector_verify(id)`, `connector_log(id, limit)` |
| 연구 | `research_state(query, tag)`, `research_add(identifier, tags)`, `research_update(id, fields)`, `research_remove(id)`, `research_bibtex(ids, tag, save)`, `research_index()`, `research_search(query, limit)`, `research_remove_document(doc_id)`, `set_vector_config(settings)`, `zotero_import_now(full)` |
| 메모리 | `memory_state(layer, query)`, `memory_add(text, layer, kind, title)`, `memory_delete_entry(id)`, `handoff_set_status(task_id, status)`, `memory_summarize_thread(thread_id)` |
| 동기화 | `sync_state()`, `sync_choose_folder()`, `sync_setup(settings)`, `sync_set_include(include)`, `sync_now()`, `sync_disconnect()`, `sync_wipe_remote()` |
| 자동화 | `automation_state()`, `set_python_settings(s)`, `set_ssh_host(alias, spec)`, `remove_ssh_host(alias)`, `python_check()` |
| 진단 | `diagnostics_state(days)`, `set_telemetry_settings(s)`, `telemetry_export_now()`, `eval_run(set, models)`, `eval_cancel()`, `feedback(thread_id, message_id, rating)` |

Python → JS 이벤트(`window.onBackendEvent`): `{"type":"connector","kind":"device_code|login_url|login_done|login_error"}`, `{"type":"hub","kind":"index_progress|index_done|index_error|sync_started|sync_done|sync_error|summary_done|summary_error|eval_progress|eval_done|eval_error"}`, 승인 요청 `{"type":"confirm", ..., "kind": edit|run|write|send|destructive|exec, "allow_session"}`.

## 2. 커넥터 MCP 서버와 도구 종류
도구 종류는 `connectors.TOOL_KINDS`가 정한다(서버의 주석은 믿지 않음). read=묻지 않음, edit=이 기기 데이터 수정, write=외부 쓰기, send·destructive·exec=항상 묻기.

| 서버 | 도구(종류) |
|---|---|
| github (19) | whoami, list_repos, search_repos, get_file, search_code, list_issues, get_issue, list_pulls, get_pull, get_pull_diff, list_commits, get_commit, list_workflow_runs, get_workflow_run, get_job_logs (read) · create_issue, update_issue, comment_issue (write) · create_pull_review (send) |
| gdrive (9) | search_files, get_file, read_file, list_folder, list_changes (read) · create_folder, create_text_file, upload_file, move_file (write) |
| gdocs (4) | read_document (read) · create_document, append_text, replace_text (write) |
| gsheets (5) | get_info, read_values (read) · update_values, append_values, create_spreadsheet (write) |
| gslides (4) | read_presentation (read) · create_presentation, add_slide, replace_text (write) |
| gmail (5) | search_messages, read_message, list_drafts (read) · create_draft (write) · send_draft (send, to·subject 재확인) |
| gcalendar (5) | list_calendars, list_events, check_conflicts (read) · create_event, update_event (write, 초대 메일 없음) |
| research (12) | library_list, library_get, extract_metadata, recommend, citation_graph, search_documents, index_status (read) · library_add, library_update, export_bibtex, index_documents (edit) · library_remove (destructive) |
| zotero (4) | search, collections (read) · import_library (edit) · add_item (write) |
| memory (8) | memory_search, project_context, handoff_list (read) · memory_write, handoff_create, handoff_accept, handoff_complete (edit) · memory_delete (destructive) |
| python (3, 데스크톱) | python_info (read) · python_run, run_notebook (exec) |
| ssh (2, 데스크톱) | hosts (read) · run (exec) |

`paper.search`에는 `source=crossref|openalex|all`이 더해졌다(도구 수는 5로 같다).

## 3. 설정 키 (`config.json`, 비밀 없음)
`features`, `connectors.<id>.{enabled,policy,options,account}`, `mcp_policy.<server>.mode`, `oauth_clients.<provider>.client_id`, `vector`, `sync`, `automation.{python,ssh}`, `telemetry.{langfuse,rates}`, `settings_updated`, `migrated_1_10`, `backup_1_10`.

## 4. 비밀 이름 (`secret_store`)
`connector:<id>:<field>`, `oauth:<id>`, `oauth_client:<provider>`, `vector:qdrant_key`, `vector:embedding_key`, `sync:key`, `langfuse:public_key`, `langfuse:secret_key`.

## 5. 데이터 파일 (데이터 폴더 아래)
`secrets.json`(폴백), `logs/tool_calls.jsonl`(30일), `logs/exec.jsonl`, `research/library.json`, `research/index.sqlite`, `memory/memory.sqlite`, `sync_state.json`, `sync-conflicts/`, `device_id`, `telemetry/events.jsonl`(90일), `evals/`, `backups/`, `connectors/gdrive_changes.json`.
