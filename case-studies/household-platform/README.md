# household-platform

> 這份案例研究來自一個實際上線、給家庭使用的全端管理平台。為了保護真實使用者（家庭成員）的隱私與正式環境的機密資訊，這裡的網域名稱、服務代號、環境變數值一律以佔位符呈現；程式碼片段是從真實程式庫中挑選、去識別化後的節錄，不是完整可運行的原始碼倉庫。

## 這是什麼

一個家庭自建的全端管理平台，涵蓋記帳、生理數據記錄、庫存管理三個功能模組，入口包含一個 LINE Bot（聊天快速記帳）與多個 LINE Mini App（React SPA）。另外有一個獨立的認證入口（Auth Portal），統一處理 LINE / Google / Email 三種登入方式，並讓使用者在多個子系統之間共享登入狀態。

## 問題陳述

家庭日常有三件事需要被有系統地追蹤：誰花了多少錢、家人的生理數據（血壓、血糖等）、消耗品庫存還剩多少、什麼時候該補貨。這些原本分散在紙本、Excel、LINE 對話裡，難以回顧與統計。這個平台把這三件事收斂成一個共用同一套認證與資料庫的系統，讓家庭成員可以用最熟悉的介面（LINE 對話、手機瀏覽器）快速記錄，同時保留完整歷史紀錄可查詢、可匯出。

## 技術棧

- **後端**：Python、FastAPI、SQLAlchemy
- **前端**：React 19、Vite、TypeScript、Tailwind CSS v4、HeroUI v3（設計系統元件庫）
- **資料庫 / 認證**：Supabase（PostgreSQL + Auth + JWKS）
- **訊息入口**：LINE Messaging API、LINE LIFF（LINE Mini App SDK）
- **部署**：Docker、雲端容器託管服務（多服務、各自獨立部署）

## 架構

完整架構圖與資料流說明另見 [architecture.md](architecture.md)。

## 關鍵挑戰與解法

### 1. 跨網域 SSO

系統拆成兩個獨立部署的服務：一個獨立的認證入口（Auth Portal）、一個家庭管理主系統（App）。兩者部署在不同的子網域下，但登入狀態必須共享——使用者在認證入口登入一次，就能直接使用主系統，不用重新登入。

解法是讓 Supabase session 的 cookie 寫在共同的父網域（例如 `.example.com`），而不是各自子網域。兩個服務各自驗證同一顆 Supabase 發出的 JWT，讀的是同一份 session，不需要額外的 SSO 協定或 token 轉發機制。詳見 [snippets/sso-cookie-strategy.md](snippets/sso-cookie-strategy.md)。

### 2. 三合一登入收斂

使用者可能透過三種路徑登入：LINE Mini App 內建的 LIFF token 交換、LINE 瀏覽器版 OAuth、或 Google / Email Magic Link（都是走 Supabase Auth）。三條路徑的憑證格式完全不同（LINE ID Token vs. OAuth Code vs. Supabase 原生 session），但最終都要收斂成同一份 Supabase JWT，才能讓後端用同一套驗證邏輯處理。

解法是把「LINE 身份」跟「Supabase 使用者」用一張對照表（LINE UID ↔ Supabase user_id）綁定，LINE 登入時如果是第一次出現的 UID，就用 Supabase Admin API 建立一個帶假 email 的 Supabase 使用者；如果已經綁定過，就直接簽發對應這個使用者的 JWT。三條路徑最後都走到同一個「拿到 user_id 之後簽 JWT / 建 session」的收斂點。詳見 [snippets/line-login-convergence.py](snippets/line-login-convergence.py)。

### 3. 多 Mini App monorepo 部署

家庭管理主系統底下有四個獨立的 React SPA（記帳、生理數據、庫存、主控台），但只想維運一個後端服務、一個部署流程。解法是把四個前端各自獨立建置（各自的 Vite dev server、各自的 base path），建置產物統一輸出到後端的靜態檔案目錄，由同一個 FastAPI 服務依路徑（`/ledger`、`/vital`、`/inventory`、`/`）分別回傳對應的前端頁面，同時服務 REST API。優點是只有一個容器、一次部署；代價是四個前端的建置流程必須被小心編排，任何一個 app 的路由 base path 設定錯誤都會讓靜態檔案對不上。

### 4. 把真實生活流程轉譯成系統設計

記帳不是單純的「輸入一筆金額」，而是有真實的家庭財務流程要對應：一筆支出從「待處理」到「已核銷（等待跟其他成員清帳）」到「已清帳」是三個不同的狀態，對應到真實生活裡「先記一筆、之後跟家人核對、最後金流真正結清」的流程。庫存管理也一樣：不是單純記錄「還剩幾個」，而是要從歷次盤點的時間間隔與數量變化，推算出「平均每天消耗多少」「大概什麼時候會用完」，並根據資料點數量與波動程度標示這個預測的信心水準（低/中/高），而不是給一個看起來很精準但其實沒有根據的數字。這一類「先理解使用者實際的生活/工作流程，再決定資料模型與狀態機怎麼設計」的思考過程，是這個系統裡最容易被低估、但實際上決定好不好用的部分。詳見 [snippets/inventory-predictor.py](snippets/inventory-predictor.py)。

### 5. UI/UX 設計系統一致性最佳化

四個 Mini App 由同一個人在不同時間點開發，很容易出現「這支 app 用藍色系、那支用紫色系」「這裡手刻一個 `<button>`、那裡用元件庫按鈕」的不一致。解法不是事後靠人眼抓，而是寫一支靜態掃描腳本，在每次改動前端程式碼後掃描是否出現原生 HTML 表單元素、寫死的 Tailwind 顏色類別（如 `bg-blue-*`）、或其他偏離設計系統慣例的模式，讓「維持視覺一致性」變成一個可以自動檢查、可以放進開發流程的步驟，而不是仰賴自律。詳見 [snippets/check-ui-contract.sh](snippets/check-ui-contract.sh)。

## 精選程式碼片段

| 檔案 | 展示重點 |
|---|---|
| [snippets/auth-jwt-middleware.py](snippets/auth-jwt-middleware.py) | Supabase JWT（ES256）驗證中介層，含模組別權限分級 |
| [snippets/line-login-convergence.py](snippets/line-login-convergence.py) | 三種登入方式收斂成同一份 Supabase JWT 的核心邏輯（節錄） |
| [snippets/sso-cookie-strategy.md](snippets/sso-cookie-strategy.md) | 跨網域 SSO 的 cookie 網域策略說明 |
| [snippets/inventory-predictor.py](snippets/inventory-predictor.py) | 消耗速率預測與信心水準計算邏輯 |
| [snippets/check-ui-contract.sh](snippets/check-ui-contract.sh) | 設計系統合規性靜態掃描腳本（原始檔案，未經修改） |

## 說明與限制

這是案例研究，不是可運行的專案。以上片段經過挑選與去識別化處理，省略了與展示重點無關的程式碼（例如管理後台的使用者角色管理端點），也移除了所有真實網域、服務名稱、GCP/雲端專案代號。目的是呈現架構決策與工程思路，不是提供可以直接部署的完整系統。

## 已知取捨

這些片段是真實生產程式碼的忠實節錄，刻意不美化，包含幾個在家庭規模的流量下可接受、但在更大規模系統裡會需要重新檢視的取捨：

- **登入收斂邏輯用同步 HTTP 呼叫 Supabase Admin API**（`line-login-convergence.py`）：每次建立/查詢使用者都同步打一次 API。對幾位家庭成員的登入頻率來說完全足夠，但如果流量放大到一般 SaaS 等級，會需要把使用者權限快取到本地資料庫，避免每次都打外部 API。
- **JWT 中介層的 JWKS 抓取用同步 `requests`**（`auth-jwt-middleware.py`）：有做快取，但首次請求仍是同步阻塞。單一小型服務可接受，非同步版本會是下一步優化方向。
- **庫存消耗速率計算沒有處理極短時間間隔**（`inventory-predictor.py`）：如果兩次盤點間隔非常短（例如手誤重複操作），理論上會讓當次消耗速率被放大，屬於一個尚未加上的邊界保護。
- **`predicted_finish_date` 假設輸入一律是 `datetime`**：如果上游傳入純 `date` 型別會出錯，目前靠呼叫端保證型別一致。

保留這些取捨而不是為了案例研究去「修好」它們，是刻意的：這份案例研究要呈現的是實際的工程判斷與已知限制，而不是一份美化過的教學範例。
