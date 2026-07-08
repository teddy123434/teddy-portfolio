# SSO Cookie 網域策略

> 這裡不放實際的前端程式碼（會牽涉真實網域設定），只說明設計思路。

## 問題

Auth Portal 跟家庭管理主系統是兩個各自獨立部署的服務（各自的容器、各自的網址）。使用者在 Auth Portal 完成登入後，應該能直接使用主系統，不需要再登入一次。

常見的做法是做一套完整的 SSO 協定（例如 OAuth2 authorization code flow、SAML），或是讓兩個服務之間互相呼叫 API 交換 token。這兩種做法都可行，但對一個只有兩個服務、且都信任同一個身份提供者（Supabase Auth）的場景來說，會是不必要的複雜度。

## 解法：共用父網域的 session cookie

兩個服務的網址都是同一個父網域下的子網域（例如 `auth.example.com` 與 `app.example.com`，父網域是 `example.com`）。Supabase 的瀏覽器端 SDK 支援自訂 cookie 儲存策略，把 session cookie 寫在 `domain=.example.com`（注意開頭的點），而不是預設的 `localStorage` 或單一子網域的 cookie。

這樣一來：

1. 使用者在 `auth.example.com` 登入，Supabase session 建立後，cookie 被寫在 `.example.com`
2. 使用者導向 `app.example.com` 時，瀏覽器會自動帶上這顆 cookie（因為 `.example.com` 涵蓋所有子網域）
3. `app.example.com` 的前端讀到同一顆 session cookie，後端用同一個 Supabase 專案驗證 JWT，不需要額外的 token 交換

## 取捨

- **優點**：不需要額外設計/維護一套 SSO 協定或 token 轉發 API；只要兩個服務都信任同一個 Supabase 專案，加一個服務進來就是「多一個子網域」的成本
- **限制**：這個做法要求所有需要共享登入狀態的服務都在同一個父網域下；如果未來有服務部署在完全不同的網域（不共用父網域），就需要換成標準 SSO 協定
- **需要注意的細節**：不能用瀏覽器預設的 `localStorage` 當作 Supabase session 儲存位置（那樣會被綁死在單一子網域），必須明確設定 cookie-based storage 並指定父網域
