# Architecture

> 網域名稱、服務代號均為佔位符，不對應任何真實環境。

## 整體架構

```mermaid
graph TD
    subgraph Client["使用者端"]
        LIFF["LINE Mini App (LIFF)"]
        Browser["瀏覽器"]
    end

    subgraph AuthPortal["Auth Portal · auth.example.com"]
        AuthAPI["FastAPI 認證服務"]
    end

    subgraph App["家庭管理主系統 · app.example.com"]
        AppFrontend["4 個獨立建置的 React Mini App<br/>(記帳 / 生理數據 / 庫存 / 主控台)"]
        AppAPI["FastAPI 後端<br/>(REST API + 靜態檔案伺服)"]
    end

    Supabase[("Supabase<br/>Auth + PostgreSQL")]
    LineAPI["LINE Messaging API"]

    LIFF -->|"LIFF ID Token 交換"| AuthAPI
    Browser -->|"LINE OAuth / Google / Magic Link"| AuthAPI
    AuthAPI --> Supabase
    AuthAPI -->|"簽發 session，cookie domain=.example.com"| Browser
    Browser -->|"共享 session cookie"| AppFrontend
    AppFrontend --> AppAPI
    AppAPI -->|"驗證 JWT (JWKS)"| Supabase
    AppAPI <-->|"Bot 訊息 / 推播提醒"| LineAPI
```

## 三合一登入收斂流程

```mermaid
flowchart LR
    A["LINE LIFF Token 交換"] --> D["Supabase 使用者<br/>(依 LINE UID 對照建立/查找)"]
    B["LINE 瀏覽器版 OAuth"] --> D
    C["Google OAuth / Email Magic Link"] --> D
    D --> E["簽發 Supabase Session<br/>cookie domain=.example.com"]
    E --> F["App 後端統一以<br/>Supabase JWT 驗證身份"]
```

## 資料流：一筆記帳如何被記錄與統計

```mermaid
sequenceDiagram
    participant U as 使用者 (LINE / Mini App)
    participant API as App 後端 (FastAPI)
    participant DB as Supabase PostgreSQL

    U->>API: 送出「500|餐飲|午餐」或 Mini App 表單
    API->>API: 驗證 Supabase JWT / LINE 訊息格式
    API->>DB: 寫入交易紀錄（狀態：待處理）
    API-->>U: 回覆確認訊息 / 畫面更新
    Note over U,DB: 之後家人核對金流，狀態轉為「已核銷」→「已清帳」
```

## 說明

- Auth Portal 與家庭管理主系統是兩個各自獨立部署的服務，各自有自己的 FastAPI 進程與資料庫連線，但共用同一個 Supabase 專案作為認證與資料的單一事實來源。
- 兩服務之間唯一的耦合點是「Supabase session cookie 的網域設定」與「JWT 驗證邏輯」，沒有額外的 token 轉發 API 或 session 同步機制，降低了跨服務通訊的複雜度。
- 家庭管理主系統內的四個 Mini App 各自是獨立的前端建置產物，但共用同一個後端 API 與同一份 JWT 驗證邏輯，只是依權限分級（見 [snippets/auth-jwt-middleware.py](snippets/auth-jwt-middleware.py)）決定各自能存取哪些模組。
