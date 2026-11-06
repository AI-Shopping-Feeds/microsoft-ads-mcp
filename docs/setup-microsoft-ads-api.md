# Getting Microsoft Advertising API access

This guide walks you through everything the server needs, without assuming you are a
developer. Allow about 20 minutes, plus waiting time for the developer token if you manage
other people's accounts.

You need three things:

1. a **developer token**, which lets your copy of the server use the API;
2. an **app registration** in Microsoft Entra ID (Azure), which identifies the server when
   you sign in;
3. a **refresh token**, created once when you sign in, which lets the server act as you.

The API only gives the server the same accounts and permissions the signed-in user already
has in the Microsoft Advertising web app.

## 1. Microsoft Advertising account and IDs

You need a Microsoft Advertising account at [ads.microsoft.com](https://ads.microsoft.com/).
Every ad account has:

- an **account ID** (a number, used as `account_id` and `MICROSOFT_ADS_ACCOUNT_ID`), and
- a **customer ID**: the manager account (customer) that owns it (`customer_id`).

In the web app, open **Campaigns** and look at the address bar: `aid=` is the account ID
and `cid=` is the customer ID. Don't confuse the account ID with the **account number**
shown in the UI (eight letters and digits); the API only uses the ID. You can also skip
this and ask the agent to run `microsoft_ads_list_accounts` once the server is connected.

## 2. Developer token

1. Sign in to Microsoft Advertising as a user with the **Super Admin** role.
2. Go to **Settings > Developer settings**
   ([ads.microsoft.com/cc/Settings/DevSettings](https://ads.microsoft.com/cc/Settings/DevSettings)).
   This replaced the old Developer Portal in 2025.
3. Choose the user to associate with the token, read and accept the terms shown, and
   select **Request Token**. Ask for a **universal** token (the default): it works with any
   user who signs in.

How long it takes: Microsoft says the token arrives immediately if you use the API for
your own accounts, and can take up to **five business days** if you manage accounts for
others. Keep the token private, like a password.

## 3. Register an app in Microsoft Entra ID

The server signs in through the Microsoft identity platform, which needs an app
registration. It works with work or school (Entra ID) accounts and personal Microsoft
accounts (Outlook.com, Hotmail and so on).

1. Open the [Azure portal app registrations](https://go.microsoft.com/fwlink/?linkid=2083908)
   and sign in with a work or school account (Microsoft no longer lets personal accounts
   register apps here). If you don't have one, a free Azure account gives you one.
2. Select **New registration**.
   - **Name**: anything, for example "Microsoft Ads MCP".
   - **Supported account types**: **Accounts in any organizational directory and personal
     Microsoft accounts** (Microsoft's guide calls it "Any Entra ID Tenant + Personal
     Microsoft accounts").
   - Leave the redirect URI empty for now and select **Register**.
3. On the app's **Overview** page, copy the **Application (client) ID**. This is
   `MICROSOFT_ADS_CLIENT_ID`.
4. Go to **Authentication > Add a platform > Mobile and desktop applications** and add
   both of these redirect URIs:
   - `http://localhost:8765/callback` (used by `microsoft-ads-mcp auth`)
   - `https://login.microsoftonline.com/common/oauth2/nativeclient` (used by
     `microsoft-ads-mcp auth --manual`)
5. You don't need a client secret or API permissions: the sign-in asks for the
   `msads.manage` permission itself.

If you will run the server on several machines with one refresh token, Microsoft
recommends a **Web** app with a client secret instead (public-client refresh tokens are
only guaranteed on the device that created them). In that case add
`http://localhost:8765/callback` as a **Web** redirect URI, create a secret under
**Certificates & secrets**, and set `MICROSOFT_ADS_CLIENT_SECRET`.

## 4. Sign in once

Run this in a terminal (it opens your browser):

```shell
MICROSOFT_ADS_CLIENT_ID=your-client-id MICROSOFT_ADS_DEVELOPER_TOKEN=your-developer-token \
  uvx --from git+https://github.com/AI-Shopping-Feeds/microsoft-ads-mcp.git microsoft-ads-mcp auth
```

Sign in with the Microsoft account that manages the ads and accept the permission request.
The server saves a refresh token to `~/.microsoft-ads-mcp/secrets/microsoft-ads-token.json`
with owner-only permissions and never prints it.

- If the browser can't reach `localhost` (a remote machine, a locked-down laptop), add
  `--manual`: after signing in you land on a blank Microsoft page; copy its full address
  and paste it into the terminal. The server checks that the address belongs to this
  sign-in (the `state` value must match).
- You can instead put the settings in `~/.microsoft-ads-mcp/.env` (see
  [.env.example](../.env.example)) and run `microsoft-ads-mcp auth` without the variables.
- Microsoft may ask you to sign in again at any time, for example after a password change
  or if you remove the app's permission. Microsoft gives 90 days as an example lifetime for
  public-client refresh tokens but promises none; the server saves the new refresh token
  Microsoft returns each time. If you see `invalid_grant`, run `auth` again.

Check the settings with `microsoft-ads-mcp describe` (it shows `"refresh_token": "set"` and
no secrets).

## 5. Try the sandbox first (optional)

Microsoft runs a separate sandbox where ads never serve.

1. Create a sandbox customer at [sandbox.bingads.microsoft.com](https://sandbox.bingads.microsoft.com)
   with an **outlook.com** Microsoft account (or a Google account), and choose **Skip
   payment information**. Work or school accounts don't work in the sandbox.
2. Set `MICROSOFT_ADS_ENVIRONMENT=sandbox`. The developer token defaults to Microsoft's
   published universal sandbox token, and you use the same app registration.
3. Run `microsoft-ads-mcp auth` and sign in with the sandbox user.

Sandbox and production credentials are separate: a production token used against the
sandbox (or the reverse) fails with error code 105. The sandbox has less capacity, only
some report types return data, and Ad Insight works for a small fixed set of keywords.

## 6. Agencies and managing other people's accounts

- Sign in with a user who has been given access to the client's account (an account link
  or a user invitation in Microsoft Advertising). The server sees exactly what that user
  sees in the web app.
- Use the client account's ID as `account_id`. The customer ID is looked up from the
  account's parent customer automatically, or pass `customer_id`.
- The Microsoft Advertising Agreement says that if you place ads for another business, you
  confirm you are authorised to act for it. Only connect accounts you are allowed to manage.
- Developer tokens for managing other people's accounts can take up to five business days.

## Troubleshooting

| Problem | Fix |
|---|---|
| `AADSTS50011` / redirect URI mismatch | Add the exact redirect URI shown by `auth` to the app registration (step 3.4). |
| `AADSTS700016` / application not found | Check `MICROSOFT_ADS_CLIENT_ID` is the GUID from the app's Overview page. |
| "not configured as a multi-tenant application" | Register the app again with "any organizational directory and personal Microsoft accounts". |
| `AADSTS650052` | Your organisation hasn't enabled Microsoft Advertising for work accounts; ask your Entra admin (Microsoft's guide explains the fix). |
| `invalid_grant` | The refresh token expired or was revoked. Run `microsoft-ads-mcp auth` again. |
| API error 105 | Token and environment don't match (production vs sandbox), or a bad developer token. |
| API error 106 | The user can't access that customer or account. Check `account_id` / `customer_id`. |
| API error 117 (CallRateExceeded) | Too many calls in a minute; the server waits 60 seconds and retries. |
| No accounts listed | Check `MICROSOFT_ADS_ENVIRONMENT` and that you signed in as the right user. |

Microsoft's own guides: [Get started](https://learn.microsoft.com/en-us/advertising/guides/get-started?view=bingads-13),
[Register an application](https://learn.microsoft.com/en-us/advertising/guides/authentication-oauth-register?view=bingads-13),
[Sandbox](https://learn.microsoft.com/en-us/advertising/guides/sandbox?view=bingads-13) and
[Handling errors](https://learn.microsoft.com/en-us/advertising/guides/handle-service-errors-exceptions?view=bingads-13).
