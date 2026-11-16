# Nghiên cứu connector LLM cho NewVideo_Push

Ngày đối chiếu: **16/11/2026**. Phạm vi: SDK, gateway và client nguồn mở để sinh kịch bản/metadata trong ứng dụng Python + Gradio. Chỉ dùng tài liệu của nhà cung cấp, mã nguồn, giấy phép và release của chính dự án. Đây là nghiên cứu tài liệu và mã nguồn; chưa đăng nhập tài khoản, cài SDK hay kiểm tra sinh nội dung trực tiếp.

## 1. Đề xuất

**Chọn hai adapter mỏng dùng `google-genai` và `openai`, đặt sau một interface nghiệp vụ chung.** Gemini là provider mặc định đề xuất vì cấu hình hiện có đã có `GEMINI_API_KEY`; OpenAI là provider tùy chọn. Chưa có benchmark để kết luận model nào viết kịch bản tiếng Việt tốt hơn hoặc rẻ hơn trong workload thực tế.

Nếu cần nhiều provider, routing/fallback tập trung hoặc chia quota giữa nhiều ứng dụng, thêm **LiteLLM** sau interface đó. Với nhu cầu thử prompt bằng giao diện chat, **LibreChat** phù hợp chạy độc lập; **Open WebUI** cũng dùng được nhưng phải đọc giấy phép branding hiện hành. Hai ứng dụng này không cần thiết để nối LLM vào Gradio.

Nếu mục tiêu thực sự là **dùng tài khoản đã đăng nhập Gemini/ChatGPT thay vì API key**, có client nguồn mở đang được duy trì: `HanaokaYuzu/Gemini-API`, `gpt4free`, và provider subscription `chatgpt/` của LiteLLM. Chúng có cơ chế xác thực, giới hạn và độ ổn định khác API công khai; không chọn làm đường sinh kịch bản mặc định cho pipeline 24/7. Chi tiết và nguồn nằm ở phần 4.

## 2. Hiện trạng repo và tiêu chí phù hợp

Đã đối chiếu các file cục bộ:

- [requirements.txt](../../requirements.txt): có Gradio, httpx, Pydantic; chưa có SDK LLM trong dependencies.
- [config.py](../../config.py): đã đọc `GEMINI_API_KEY` từ environment; chưa có `OPENAI_API_KEY`, model/provider selection hay connector.
- [app.py](../../app.py) và [ui/views.py](../../ui/views.py): entry point/UI hiện có, chưa phải engine sinh kịch bản.
- [CLAUDE.md](../../CLAUDE.md): Python 3.10+, `core/` độc lập Gradio, xử lý mạng có timeout/retry, không ghi credential ra log; mục tiêu cloud/container tài nguyên hạn chế.
- [TECHNICAL_DESIGN.md](../TECHNICAL_DESIGN.md), §9.1 và DEC-010: worker sinh kịch bản khi input là prompt; input có script thì bỏ qua LLM; provider chính và luồng thiếu API key còn là quyết định mở.

Vì vậy ưu tiên thư viện Python async nhẹ, output có schema, xác thực từ server và khả năng chạy headless. Khả năng dùng lại cookie từ trình duyệt Windows không đồng nghĩa chạy bền trong container Linux.

## 3. Nhóm A: API chính thức và gateway

| Lựa chọn / repo | Giấy phép; ngôn ngữ | Cách tích hợp, Gemini / OpenAI | Đánh giá cho repo này |
|---|---|---|---|
| [Google Gen AI Python SDK](https://github.com/googleapis/python-genai) (`google-genai`) | Apache-2.0; Python. [License](https://github.com/googleapis/python-genai/blob/main/LICENSE) | Gemini Developer API bằng API key; cũng hỗ trợ nền tảng Google Cloud bằng credential tương ứng. Có async, streaming, structured output. Không phải client OpenAI. [README](https://github.com/googleapis/python-genai/blob/main/README.md) | **Ưu tiên cho Gemini native**, ít tầng trung gian, phù hợp kịch bản JSON và mở rộng multimodal. |
| [OpenAI Python SDK](https://github.com/openai/openai-python) (`openai`) | Apache-2.0; Python. [License](https://github.com/openai/openai-python/blob/main/LICENSE) | OpenAI API key; `AsyncOpenAI`, Responses API, streaming và output có kiểu. Có thể gọi Gemini bằng endpoint tương thích của Google, không phải bằng cookie ChatGPT. [README](https://github.com/openai/openai-python/blob/main/README.md), [Google compatibility](https://ai.google.dev/gemini-api/docs/openai) | **Ưu tiên cho OpenAI**. Một client dùng hai endpoint là phương án tối giản nếu chỉ cần text, nhưng cần kiểm tra feature parity. |
| [LiteLLM](https://github.com/BerriAI/litellm) | Core MIT; `litellm/enterprise/` có giấy phép riêng. Backend/SDK Python, dashboard có TypeScript. [License](https://github.com/BerriAI/litellm/blob/main/LICENSE), [source](https://github.com/BerriAI/litellm/tree/main/litellm) | Python SDK trong process hoặc proxy HTTP tương thích OpenAI. Hỗ trợ `gemini/` dùng Gemini API key, `vertex_ai/` dùng credential Cloud và OpenAI API. [Gemini](https://docs.litellm.ai/docs/providers/gemini), [OpenAI](https://docs.litellm.ai/docs/providers/openai) | **Tốt khi số provider/quota tăng**. SDK đủ cho MVP đa provider; proxy thêm service, cấu hình và vận hành. Không cần đưa proxy vào MVP chỉ để đổi Gemini/OpenAI. |
| [LibreChat](https://github.com/LibreChat-AI/LibreChat) | MIT; TypeScript/JavaScript, React/Node. Repo cũ `danny-avila/LibreChat` redirect sang tổ chức mới. [License](https://github.com/LibreChat-AI/LibreChat/blob/main/LICENSE), [source](https://github.com/LibreChat-AI/LibreChat) | Ứng dụng chat self-host dùng provider API. Cấu hình Google/Gemini và OpenAI bằng key/credential; không tự tận dụng phiên ChatGPT/Gemini cá nhân. [Google](https://www.librechat.ai/docs/configuration/pre_configured_ai/google), [OpenAI](https://www.librechat.ai/docs/configuration/pre_configured_ai/openai) | Hợp làm phòng thử prompt cho người vận hành. Không phải SDK để import vào Python; stack mẫu có MongoDB và các dịch vụ tìm kiếm/RAG. [Compose](https://github.com/LibreChat-AI/LibreChat/blob/main/docker-compose.yml) |
| [Open WebUI](https://github.com/open-webui/open-webui) | Python/FastAPI backend; Svelte/TypeScript frontend. **Open WebUI License** hiện hành, kèm lịch sử license; có điều khoản giữ branding và ngoại lệ nêu trong license. [License](https://github.com/open-webui/open-webui/blob/main/LICENSE), [backend](https://github.com/open-webui/open-webui/blob/main/backend/open_webui/main.py), [frontend](https://github.com/open-webui/open-webui/blob/main/package.json) | UI self-host; OpenAI và Gemini qua API tương thích OpenAI, hoặc middleware/pipe. Có REST endpoint `/api/chat/completions` với Bearer auth. [Provider guide](https://docs.openwebui.com/getting-started/quick-start/connect-a-provider/starting-with-openai-compatible/), [API](https://docs.openwebui.com/reference/api-endpoints/) | Hợp nếu đã vận hành Open WebUI và cần dùng lại cấu hình/model. Thêm UI/database và một hop mạng nếu chỉ dùng làm connector; API docs tự cảnh báo interface thay đổi thường xuyên. |

### Tín hiệu duy trì đã kiểm tra

Các repo ứng viên trong bảng đều chưa bị archive tại thời điểm kiểm tra. Dữ liệu release/commit lấy trực tiếp từ GitHub API công khai; release có thể chậm hơn nhánh chính và không phải bằng chứng endpoint hoạt động với mọi tài khoản.

| Dự án | Release quan sát được | Commit đầu nhánh mặc định quan sát được |
|---|---|---|
| google-genai | [v3.3.0, 12/11/2026](https://github.com/googleapis/python-genai/releases/tag/v3.3.0) | [36c3c5f, 16/11/2026](https://github.com/googleapis/python-genai/commit/36c3c5fada2ccbf166dfc66fa7b58516f9ddef5e) |
| openai-python | [v3.51.0, 13/11/2026](https://github.com/openai/openai-python/releases/tag/v3.51.0) | [3dae609, 13/11/2026](https://github.com/openai/openai-python/commit/3dae6090cc31cc64a437fe0bcee740b6d81ed2cc) |
| LiteLLM | [v1.109.1, 12/11/2026](https://github.com/BerriAI/litellm/releases/tag/v1.109.1), stable theo endpoint `/releases/latest`; đồng thời có các bản dev mới hơn | [d034fb6, 16/11/2026](https://github.com/BerriAI/litellm/commit/d034fb681ca296a0f082a224043eda62a2ce82d4) |
| LibreChat | [v0.8.9-rc1, 26/10/2026](https://github.com/LibreChat-AI/LibreChat/releases/tag/v0.8.9-rc1), prerelease | [9363db5, 15/11/2026](https://github.com/LibreChat-AI/LibreChat/commit/9363db541ecd4e23ab6a41dca47ca48ee2bd418e) |
| Open WebUI | [v0.13.3, 08/11/2026](https://github.com/open-webui/open-webui/releases/tag/v0.13.3) | [b0e6098, 08/11/2026](https://github.com/open-webui/open-webui/commit/b0e6098e940942281d9c83f3529ea117287a3a22) |

### Các giới hạn cần xử lý khi chọn API

**Phiên bản Python:** `google-genai` v3.3.0 yêu cầu **Python >=3.11**, còn `openai` v3.51.0 yêu cầu **>=3.10**. Khuyến nghị nâng runtime dự án lên 3.11+ trước khi chọn SDK Google mới; nếu giữ 3.10 phải xác minh/pin bản tương thích. Hai SDK mới cũng có dependency HTTP riêng cần resolve cùng requirements hiện có, không giả định cài trên môi trường cũ sẽ thành công. [Google pyproject tại release](https://github.com/googleapis/python-genai/blob/v3.3.0/pyproject.toml), [OpenAI pyproject tại release](https://github.com/openai/openai-python/blob/v3.51.0/pyproject.toml)

**Đúng SDK Google:** dùng `google-genai`; `google-generativeai` là thư viện legacy không còn được duy trì tích cực theo bảng migration của Google. [Google libraries](https://ai.google.dev/gemini-api/docs/libraries)

**Một protocol không đảm bảo mọi tính năng giống nhau:** Google có endpoint chính thức `https://generativelanguage.googleapis.com/v1beta/openai/` dùng Gemini key với OpenAI SDK. Đây là compatibility API, không phải ChatGPT session. Không mặc định Responses API hay tất cả tính năng native đều được hỗ trợ như OpenAI. [Tài liệu Google](https://ai.google.dev/gemini-api/docs/openai)

Open WebUI hiện cảnh báo Gemini streaming tool calling có khác biệt schema và thought signature; chat text có thể chạy trong khi turn gọi tool trả lời trống. Vì vậy không suy từ “chat thành công” sang “tools/JSON/multimodal đều tương thích”; với Open WebUI cần gateway dịch native hoặc giải pháp được guide chỉ rõ. [Provider guide của Open WebUI](https://docs.openwebui.com/getting-started/quick-start/connect-a-provider/starting-with-openai-compatible/)

**License Open WebUI:** bản hiện tại có hạn chế thay đổi/xóa branding, với ngoại lệ deployment không quá 50 người dùng trong một cửa sổ 30 ngày, hoặc được cấp quyền/license phù hợp. Không ghi dự án hiện tại đơn giản là “MIT/BSD”; code cũ giữ license gốc theo lịch sử. [LICENSE](https://github.com/open-webui/open-webui/blob/main/LICENSE)

**Chi phí và dữ liệu:** SDK nguồn mở không làm dịch vụ model miễn phí. ChatGPT và OpenAI API có hệ thống billing riêng; một số gói đủ điều kiện có thể có API credit khuyến mại, nhưng subscription không tự biến thành API usage không giới hạn. [OpenAI billing](https://help.openai.com/en/articles/9039756-managing-billing-for-chatgpt-and-the-api-platform)

Gemini có unpaid quota tùy model/project; điều khoản unpaid cho phép dùng input/output để cải tiến và có human review, với ngoại lệ địa lý nêu trong terms. Paid có điều khoản dữ liệu khác. Không gửi tài liệu mật vào free tier theo giả định đó là zero retention. [Gemini terms](https://ai.google.dev/gemini-api/terms)

OpenAI API không dùng dữ liệu API để huấn luyện theo mặc định trừ khi opt-in, nhưng chính sách retention còn tùy endpoint và cấu hình. `store=False` không đồng nghĩa mọi abuse log đều biến mất. Chính sách purge video cục bộ của dự án không phải cam kết xóa dữ liệu trên provider. [OpenAI data controls](https://developers.openai.com/api/docs/guides/your-data)

## 4. Nhóm B: dùng phiên/tài khoản web

### Gemini: HanaokaYuzu/Gemini-API

- **Repo:** [HanaokaYuzu/Gemini-API](https://github.com/HanaokaYuzu/Gemini-API), package `gemini_webapi`, Python async; yêu cầu Python >=3.11. Giấy phép hiện tại là **AGPL-3.0**. [pyproject](https://github.com/HanaokaYuzu/Gemini-API/blob/master/pyproject.toml), [LICENSE](https://github.com/HanaokaYuzu/Gemini-API/blob/master/LICENSE)
- **Cơ chế:** reverse-engineer Gemini web, dùng cookie phiên Google như `__Secure-1PSID` / `__Secure-1PSIDTS`; hỗ trợ refresh cookie, chat/streaming và các capability theo tài khoản. Có tùy chọn đọc cookie trình duyệt; không cần API key. Chỉ Gemini, không có OpenAI. Đây là thông tin dự án công bố, chưa được xác nhận bằng gọi model trong nghiên cứu này. [README](https://github.com/HanaokaYuzu/Gemini-API/blob/master/README.md)
- **Duy trì:** [v2.1.1, 27/08/2026](https://github.com/HanaokaYuzu/Gemini-API/releases/tag/v2.1.1); [commit f14269a, 10/11/2026](https://github.com/HanaokaYuzu/Gemini-API/commit/f14269ab3271f7d481191610195bd8c9ffee02e4), commit đầu nhánh là cập nhật dependency CI. Có hoạt động gần đây, nhưng không dùng riêng commit này để kết luận protocol vừa được sửa hay đang hoạt động.
- **Rủi ro vận hành:** cookie là quyền truy cập tài khoản; refresh cần file ghi được/persistence qua rebuild. README cảnh báo cookie từ Chromium có thể bị ràng buộc thiết bị, hết hiệu lực nhanh và không renew được; không có SLA cho endpoint nội bộ. [Cookie notes](https://github.com/HanaokaYuzu/Gemini-API/blob/master/README.md#authentication)
- **ToS/fit:** suy luận kỹ thuật: rủi ro gián đoạn và lộ tài khoản cao hơn API key có phạm vi dự án. Google cấm bypass biện pháp bảo vệ và truy cập tự động trái chỉ dẫn máy đọc; không thể kết luận mọi automation đều bị cấm chỉ từ điều khoản tổng quát. [Google terms](https://policies.google.com/terms?hl=en&gl=vn) AGPL có nghĩa vụ source tương ứng khi sửa phần covered work và cung cấp qua mạng; cần xét cách ghép/phân phối trước khi import vào ứng dụng. [License §13](https://github.com/HanaokaYuzu/Gemini-API/blob/master/LICENSE) Chỉ cân nhắc thử nghiệm opt-in tách biệt.

### ChatGPT và Gemini: gpt4free / g4f

- **Repo:** [xtekky/gpt4free](https://github.com/xtekky/gpt4free), core Python; có JS client/GUI và Go launcher; **GPL-3.0**, xem license/header của phần sử dụng. Có SDK và server tương thích OpenAI. [README](https://github.com/xtekky/gpt4free/blob/main/README.md), [LICENSE](https://github.com/xtekky/gpt4free/blob/main/LICENSE)
- **Support có source:** có provider [`OpenaiChat`](https://github.com/xtekky/gpt4free/blob/9059e300bdd71a02973107805933cd882040de4b/g4f/Provider/needs_auth/OpenaiChat.py) gọi `chatgpt.com` bằng token/cookie/browser/HAR và [`Gemini`](https://github.com/xtekky/gpt4free/blob/9059e300bdd71a02973107805933cd882040de4b/g4f/Provider/needs_auth/Gemini.py) gọi endpoint web Gemini. Đồng thời có provider API chính thức/third-party khác; “g4f” không đồng nghĩa request nào cũng đi thẳng Google/OpenAI.
- **Duy trì:** [v8.9.3, 11/11/2026](https://github.com/xtekky/gpt4free/releases/tag/v8.9.3); [commit 9059e30 cùng ngày](https://github.com/xtekky/gpt4free/commit/9059e300bdd71a02973107805933cd882040de4b). `OpenaiChat` có cờ `working=True`, chỉ là trạng thái trong source, không phải kết quả kiểm thử độc lập hay cam kết mọi account/model.
- **Vận hành/an toàn:** tài liệu yêu cầu bảo vệ HAR/cookie; browser automation tăng RAM và dependency. Việc chọn provider tự động làm khó kiểm soát nơi nhận prompt/model thật; nếu thử nghiệm phải allowlist provider/host, khóa version, không fallback sang dịch vụ lạ. Đây là đánh giá kiến trúc từ cơ chế router và lưu auth của dự án. [README](https://github.com/xtekky/gpt4free/blob/main/README.md), [auth docs](https://github.com/gpt4free/g4f.dev/blob/main/docs/config.md)
- **ToS/fit:** OpenAI consumer Terms cấm tự động trích xuất output và bypass giới hạn/biện pháp bảo vệ; do đó scraping ChatGPT có rủi ro rõ ràng về điều khoản và tài khoản. [OpenAI Terms](https://openai.com/policies/terms-of-use/) GPL có nghĩa vụ khi phân phối covered/combined work; không tự đồng nhất với AGPL network clause. [GPL tại repo](https://github.com/xtekky/gpt4free/blob/main/LICENSE) Không đề xuất cho worker sản xuất.

### Trường hợp khác: LiteLLM `chatgpt/` dùng subscription Codex

Đây là **provider bên thứ ba dùng OAuth device flow**, khác với `openai/` API key và khác việc lấy cookie/HAR từ tab ChatGPT. Nó dùng backend ChatGPT/Codex và model mà subscription/workspace cấp quyền. OpenAI có tài liệu về đăng nhập ChatGPT/device code cho Codex, nhưng tài liệu đó không tự chứng nhận mọi gateway hoặc mọi workload trên backend là API tích hợp được hỗ trợ. [LiteLLM provider](https://docs.litellm.ai/docs/providers/chatgpt), [OpenAI auth](https://learn.chatgpt.com/docs/auth)

LiteLLM hướng dẫn login tương tác trước khi chạy async worker/proxy, lưu `auth.json` ghi được để refresh; cần xử lý re-login khi token bị thu hồi. Tài liệu mô tả token mặc định dùng chung cho process và rủi ro nhiều worker refresh đồng thời. Source hiện tại cũng có tùy chọn đường dẫn auth riêng, nên cần audit đúng version nếu muốn nhiều account, không suy rằng virtual API key tự tạo credential isolation. [Provider docs](https://docs.litellm.ai/docs/providers/chatgpt), [authenticator source](https://github.com/BerriAI/litellm/blob/d034fb681ca296a0f082a224043eda62a2ce82d4/litellm/llms/chatgpt/authenticator.py)

Đánh giá: phù hợp khảo sát có kiểm soát khi yêu cầu bắt buộc dùng subscription; **không** chọn mặc định cho video pipeline. Khả năng giới hạn token, quota và auth không giống OpenAI API; dùng SDK/gateway nguồn mở không làm mất các điều khoản của dịch vụ upstream. License core vẫn là MIT/phần enterprise có license riêng như phần 3. Không gọi chung OAuth device login và cookie scraping là cùng một cơ chế.

### Dự án cũ bị loại

[`acheong08/ChatGPT` / revChatGPT](https://github.com/acheong08/ChatGPT) đã archive; [commit cuối quan sát được 02/08/2023](https://github.com/acheong08/ChatGPT/commit/9167b325addc7d3520987face684e8230bd62b46), release 6.8.6 từ 20/07/2023. Không dùng như connector ChatGPT đang được duy trì trong năm 2026.

## 5. Kiến trúc adapter đề xuất

Phần này là **thiết kế đề xuất**, chưa tạo module hoặc thay đổi runtime.

```text
Gradio UI
   -> VideoWorkflow / worker
      -> ScriptService (persona, prompt version, validate output)
         -> LlmProvider (Protocol)
            -> GeminiApiProvider        -> google-genai async
            -> OpenAIApiProvider         -> AsyncOpenAI Responses
            -> OpenAICompatibleProvider -> endpoint đã allowlist
            -> LiteLlmProvider          -> SDK/proxy, khi có nhu cầu
```

| Thành phần dự kiến | Trách nhiệm |
|---|---|
| `core/llm/contracts.py` | `LlmRequest`, `LlmResult`, `LlmCapabilities`, lỗi chuẩn hóa; dùng dataclass/Pydantic, không import Gradio hay SDK provider. |
| `core/llm/providers/gemini_api.py` | Map request sang native Gemini async; chuẩn hóa text/JSON, usage, refusal và finish reason. |
| `core/llm/providers/openai_api.py` | Gọi Responses API bằng server-side key; không đọc cookie từ máy người dùng. |
| `core/llm/providers/openai_compatible.py` | Chat Completions compatibility cho gateway/Google nếu chọn; capability matrix tách khỏi Responses. Không cho client public tự nhập URL tùy ý. |
| `core/script_service.py` | Prompt theo channel persona; output `ScriptDraft` gồm narration, scenes/stock keywords và metadata; kiểm schema, độ dài và trạng thái bị cắt/refusal trước TTS. |
| `config.py` / composition root | Chọn provider/model và secret reference; tạo/inject adapter một lần, đóng HTTP client khi shutdown. |

Interface tối thiểu: `async generate(request: LlmRequest) -> LlmResult`. Chỉ thêm `stream()` nếu UI cần; worker dựng video dùng kết quả hoàn chỉnh đã validate. `LlmResult` chứa provider/model thực tế, text/structured data, token usage nếu có, request ID và trạng thái hoàn thành; không chứa auth/raw SDK object. Capability flags quyết định có dùng structured output/tool/image hay không thay vì giả định provider nào cũng nhận cùng tham số.

Cấu hình dự kiến: `LLM_PROVIDER`, `LLM_MODEL`, `LLM_TIMEOUT_SECONDS`, `LLM_MAX_OUTPUT_TOKENS`, `GEMINI_API_KEY`, `OPENAI_API_KEY`; endpoint tùy chọn chỉ do admin/server cấu hình. Key/refresh token/cookie không xuất hiện trong Channel Profile, job snapshot, prompt, thông báo lỗi hay log. Chưa cần UI lưu credential riêng khi chưa có mô hình xác thực/secret store.

Luồng lỗi và fallback:

1. Input đã là script: bỏ qua LLM, tiếp tục TTS theo thiết kế hiện có. Input là prompt nhưng thiếu key: trả lỗi cấu hình rõ ràng và cho nhập script thủ công.
2. Đặt timeout theo từng provider và deadline toàn bước. Retry có backoff+jitter cho timeout/429/5xx trong ngân sách hữu hạn; chọn một tầng sở hữu retry để tránh SDK retry nhân với service retry. Không retry mù 401/403, schema sai hoặc refusal.
3. Output trống, bị cắt, sai schema hoặc vượt giới hạn không được coi là script thành công. Giới hạn số lần sửa JSON; người dùng có thể sửa script thủ công.
4. Fallback sang provider khác chỉ khi đã cấu hình và chấp nhận chi phí/nơi xử lý dữ liệu; không âm thầm đổi sang cookie backend hay dịch vụ trung gian miễn phí.
5. Snapshot script đã duyệt/prompt hash + model/prompt version theo job để resume không sinh lại ngoài ý muốn; giới hạn concurrency LLM độc lập với FFmpeg. LLM không có quyền tự publish hoặc gọi shell.

Nếu vẫn cần thử web session: thêm adapter experimental ở **process/service riêng**, credential riêng từng tài khoản, chỉ bind private/local, có feature flag tắt mặc định và trạng thái `REAUTH_REQUIRED`. Không tự chạy browser login trong Gradio callback; không đưa HAR vào workspace/cache upload và không giả định tách process tự giải quyết mọi nghĩa vụ license. Đây là phương án thử nghiệm, không nằm trên đường fallback tự động của MVP.

## 6. Kế hoạch xác minh trước khi triển khai

1. Chốt Python 3.11+, resolve/pin SDK và dependencies trong môi trường sạch giống container đích. Dùng model ID lấy từ provider/account thực tế; không hardcode tên model từ README cũ.
2. Contract tests với fake provider: input script bỏ qua LLM, thiếu key, output hợp lệ/sai schema/bị cắt, refusal, timeout, 429, 401 và fallback được cấu hình. Kiểm tra không có secret trong lỗi/log/snapshot.
3. Smoke test bằng key được cấp riêng: một prompt tiếng Việt, một output structured, một request stream nếu UI dùng; đo latency/token và đánh giá narration/scene keywords. Với compatibility endpoint, test riêng schema/tool path cần dùng.
4. Xác nhận SDK client được đóng, job retry không sinh trùng và quota hết vẫn có luồng nhập script. Giữ Review Gate trước publish.

Nghiên cứu này không thực hiện các smoke test cần credential, không benchmark chất lượng/giá model và không xác nhận endpoint web hoạt động. Chỉ tạo báo cáo; không sửa dependencies, config hay code ứng dụng.
