# LMCache KV Cache 記憶體追蹤（Memory Trace）與 CSV 匯出說明

本文件完整說明本分支針對 LMCache 所做的觀測／記錄改動，重點包含：

- 在資料層事件中回傳實際讀寫的位址（address）與大小（size）。
- 以 CSV 檔記錄 KV Cache 記憶體 trace，供 CXL-SSD 模擬器或後續分析使用。
- 事件定義、欄位規格、啟用方式與範例。


適用範圍：本文件聚焦於資料層 I/O 事件，特別是 `kv_cache_hit`、`kv_cache_offload_to_host`、`memory_allocation`、`memory_deallocation`；元資料層事件（如 `kv_cache_miss`）不會產生儲存 I/O，因此不寫入 CSV。

---

## 1. 設計目標與原則

- 高保真：事件中的 address 與 size 直接對應到 KV 區塊（MemoryObj）在後端儲存（例如 CXL-SSD）上的實際位置與容量，以便準確模擬讀寫延遲與頻寬。
- 低入侵：在不改變 LMCache 功能與對外 API 的前提下，於關鍵路徑插入事件鉤子（hooks）與簡單序列化，避免影響推論效能。
- 易分析：採用 CSV 純文字格式，欄位固定且有版本號，便於以 pandas、Excel、或自有模擬器直接載入。

---

## 2. 事件模型（Events Model）

我們將 LMCache 內部可對應儲存 I/O 的行為，定義為以下事件。每筆事件都會被序列化至 CSV（詳見第 4 節）。

資料層事件（會產生儲存 I/O，會記錄 CSV）：

- kv_cache_hit: 讀取一個完整的 MemoryObj（區塊）至 GPU。
- kv_cache_offload_to_host: 將 MemoryObj 從 GPU/主記憶體寫出到後端儲存。
- memory_allocation: 在後端儲存空間分配一塊用於存放 MemoryObj 的區域。
- memory_deallocation: 釋放先前分配的區域。

元資料層事件（不產生儲存 I/O，不記錄 CSV）：

- kv_cache_miss: 在 hot_cache 索引查找失敗，僅屬 CPU/DRAM 字典查詢，不會觸發實體 I/O。

---

## 3. Address 與 Size 的來源與保證

- Address 來源：
  - 讀（hit/load）與寫（offload）事件的 address 由儲存後端（storage backend / storage manager）回傳，對應 MemoryObj 在後端儲存中的起始位址（或頁框映射起點）。
  - allocation/deallocation 事件的 address 則對應新分配或即將釋放的區域起始位址。
- Size 來源：
  - 以 MemoryObj 的實佔大小為準（等價於 `memory_obj.get_size()`），LMCache 以「區塊（chunk）」為最小單位，無預留空洞，故 size 即為實際有效資料量。
- 保證：
  - kv_cache_hit 期間，應用層會傳輸整個 MemoryObj 至 GPU，非子區段；因此 CSV size 應等於區塊完整大小。

---

## 4. CSV 格式規格（Schema）

- 檔案格式：UTF-8、逗號分隔、首列為標頭。
- 版本：以 `schema_version` 欄位標示，便於未來向前/向後相容。

欄位定義：

- timestamp_ns: 整數，事件產生的單調時間（ns），可用於排序與相對延遲估計。
- event: 字串，事件名稱。可為 {kv_cache_hit, kv_cache_offload_to_host, memory_allocation, memory_deallocation}。
- request_id: 字串/整數，關聯同一高層請求（推論序列）的事件。
- seq_id: 整數，序號或 step 記錄（可選）。
- address: 以 0x 前綴的十六進位字串或整數，代表後端儲存的起始位址（或頁框基址）。
- size_bytes: 整數，操作區塊大小（等於 MemoryObj 大小）。
- chunk_size: 整數，LMCache chunk size（tokens），便於將 size 與形狀推導對齊（可選）。
- kv_dtype: 字串，KV dtype（如 fp16/bf16），便於還原實佔大小（可選）。
- layer_count: 整數，涉及的層數（可選）。
- head_count: 整數，涉及的頭數（可選）。
- token_count: 整數，區塊內 token 數量（可選）。
- schema_version: 字串，目前為 "1.0"。
- extra: JSON 字串，供擴充（slot mapping 片段、shard info、node rank 等）。

標頭（建議）：

```text
timestamp_ns,event,request_id,seq_id,address,size_bytes,chunk_size,kv_dtype,layer_count,head_count,token_count,schema_version,extra
```

範例列：

```text
780123456789,kv_cache_hit,req-42,17,0x7f2a000000,2097152,128,bf16,32,32,128,1.0,"{\"tp_rank\":0,\"pp_rank\":0}"
780123556111,kv_cache_offload_to_host,req-42,18,0x7f3c800000,2097152,128,bf16,32,32,128,1.0,"{\"reason\":\"evict\"}"
780123600000,memory_allocation,allocator,0,0x7f4d000000,268435456,128,bf16,32,32,0,1.0,"{\"pool\":\"kv\"}"
780223600999,memory_deallocation,allocator,0,0x7f4d000000,268435456,128,bf16,32,32,0,1.0,"{\"pool\":\"kv\"}"
```

---

## 5. 檔案輸出與輪轉（File Output & Rotation）

- 預設輸出位置：專案根目錄或由環境變數指定（見第 6 節）。
- 檔名慣例：`kv_cache_memory_trace_<YYYYmmdd_HHMMSS>.csv`。
- 輪轉策略：
  - 依檔案大小（例如 512MB）或依時間（例如每小時）切檔。
  - 生成新檔時續寫標頭，避免解析端需共享 schema 狀態。
- 併發：
  - 多進程/多節點建議各自輸出一份檔案，檔名可追加 rank 後綴：`..._tp{tp}_pp{pp}_rank{rank}.csv`。
  - 若需單檔合併，建議以多程序安全的 queue/pipe 送至單 writer，或啟用檔案鎖。

---

## 6. 啟用方式（Configuration）

支援以環境變數或程式參數啟用。若兩者同時存在，程式參數優先。

環境變數（建議）：

- LMC_TRACE_ENABLE=true|false
- LMC_TRACE_OUTPUT_DIR=<目錄路徑>
- LMC_TRACE_ROTATE_MAX_BYTES=<整數，預設 536870912>
- LMC_TRACE_ROTATE_INTERVAL_SEC=<整數，預設 0 表示僅依大小>
- LMC_TRACE_INCLUDE_FIELDS=<以逗號分隔欄位清單，空則全寫>

程式參數（若有對應 Config）：

- CacheEngineConfig 或觀測 Config 中加入：
  - trace_enable: bool
  - trace_output_dir: str
  - trace_rotate_max_bytes: int
  - trace_rotate_interval_sec: int
  - trace_include_fields: List[str]

最小化啟用範例（環境變數）：

```powershell
$env:LMC_TRACE_ENABLE = "true"
$env:LMC_TRACE_OUTPUT_DIR = ".\traces"
```

---

## 7. 事件寫入時機（Instrumentation Hooks）

下列為各事件建議插點，實作時請以實際程式碼為準：

- kv_cache_hit：
  - 位置：在 `storage_manager.get(key)` 取得 `memory_obj` 後（可取得 address/size），且在 `gpu_connector.to_gpu(memory_obj, ...)` 前後皆可記錄；若需區分提交與完成，可分兩筆事件（start/complete）。
  - address：由 `memory_obj` 或其後端句柄回傳的起始位址。
  - size_bytes：`memory_obj.get_size()`。

- kv_cache_offload_to_host：
  - 位置：在 offload 路徑即將提交寫入後端儲存時，並於完成後可補寫一筆完成事件（可選）。

- memory_allocation / memory_deallocation：
  - 位置：在儲存後端 allocator 分配／釋放空間成功後紀錄（可在 storage backend 層集中實作）。

注意：

- kv_cache_miss 不寫 CSV（僅元資料索引查找失敗）。
- 為降低 overhead，建議將 CSV writer 置於背景 thread/async queue，主路徑只 enqueue 結構化事件。

---

## 8. 使用範例

### 8.1 推論時啟用追蹤

- 設定環境變數：

```powershell
$env:LMC_TRACE_ENABLE = "true"; $env:LMC_TRACE_OUTPUT_DIR = ".\traces"
```

- 以現有腳本啟動 vLLM/LMCache。執行結束後，於 `.\traces` 目錄可看到 `kv_cache_memory_trace_*.csv`。

### 8.2 以 pandas 載入分析

```python
import pandas as pd

df = pd.read_csv("traces/kv_cache_memory_trace_20250801_120000.csv")

# 僅看讀事件
reads = df[df.event == "kv_cache_hit"].copy()
reads["MB"] = reads.size_bytes / (1024*1024)
print(reads[["timestamp_ns", "address", "MB"]].head())
```

---

## 9. 與 CXL-SSD 模擬的對接

- 模擬端可將單筆事件視為一個「宏觀請求」；
- 再於模擬內部切分為 4KB 頁面級別，模擬 DRAM cache 命中/未命中與 SSD 讀寫；
- kv_cache_hit -> Read；kv_cache_offload_to_host -> Write；allocation/deallocation -> 管理操作；
- CSV 欄位中的 address/size 可直接當作模擬器請求的目標與負載大小。

---

## 10. 效能與開銷（Overhead）

- 事件序列化：以背景批次寫入，千級 QPS 下通常 <1% overhead；極端情況可調降事件欄位或取樣率（未來可新增 `LMC_TRACE_SAMPLE_RATE`）。
- I/O：推薦使用獨立磁碟或 NVMe/CXL-SSD 作為 trace 輸出目標，以免干擾主工作負載。

---

## 11. 相容性與版本

- schema_version=1.0：本版欄位如第 4 節所述。
- 未來可能新增：
  - start_ts_ns / end_ts_ns 以拆分提交與完成；
  - device/node 拓撲（tp/pp/tensor_parallel、rank）；
  - 取樣率與事件聚合（roll-up）。

---

## 12. 疑難排解（FAQ）

- 為什麼 `kv_cache_miss` 沒有出現在 CSV？
  - 因為 miss 僅是索引查找失敗，不會觸發後端 I/O；屬於元資料操作。
- 為什麼 `kv_cache_hit` 的 size 總是等於 MemoryObj 大小？
  - LMCache 以「區塊」為原子單位，hit 後會搬移整塊資料到 GPU，而非分段搬移。
- address 是虛擬位址還是裝置位址？
  - 依儲存後端實作而定；本 trace 將其視為「能唯一映射到儲存位置的基址」，模擬器僅需保序與對應即可。

---

## 13. 變更摘要（Changelog for Trace 功能）

- 在資料層事件路徑新增 hooks，回傳/收集 address 與 size。
- 新增 CSV writer 與檔案輪轉機制。
- 新增環境變數與（可選）Config 欄位以啟用與配置。
- 文件：新增本說明檔 `KV_CACHE_MEMORY_TRACE.md`。

---

## 14. 參考與延伸閱讀

- CXL-SSD 模擬與分頁級行為建議，見 `CXL_SSD_SIMULATION_NOTES.md`。
- vLLM/LMCache 相關程式碼路徑（實際以本分支為準）：
  - `lmcache/v1/cache_engine.py`
  - `lmcache/v1/gpu_connector.py`
  - `lmcache/storage_backend/*`（若有）
