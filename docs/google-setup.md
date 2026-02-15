# Google Cloud Setup Guide

This guide walks you through creating a Google Cloud project, enabling the required APIs, and configuring OAuth 2.0 credentials so the mail client can access Gmail and Google Calendar on your behalf.

## Overview

The mail client uses Google APIs for three purposes:

| Purpose | APIs Used | Scopes |
| --- | --- | --- |
| **User login** | Google Identity (OpenID Connect) | `openid`, `userinfo.email`, `userinfo.profile` |
| **Email access** | Gmail API | `gmail.readonly`, `gmail.send`, `gmail.modify`, `gmail.labels` |
| **Calendar access** | Google Calendar API | `calendar.readonly` |

All scopes are requested at the time a Gmail account is connected. The login flow only requests basic identity scopes.

---

## Step 1: Create a Google Cloud Project

1. Go to the [Google Cloud Console](https://console.cloud.google.com/).
2. Click the project dropdown at the top of the page and select **New Project**.
3. Give your project a name (e.g. "Mail Client") and click **Create**.
4. Make sure your new project is selected in the project dropdown before continuing.

## Step 2: Enable the Required APIs

You need to enable three APIs. Navigate to **APIs & Services > Library** (or use the links below) and click **Enable** for each one:

1. **Gmail API**
   - [Enable Gmail API](https://console.cloud.google.com/apis/library/gmail.googleapis.com)
   - Required for reading, sending, and managing email messages and labels.

2. **Google Calendar API**
   - [Enable Google Calendar API](https://console.cloud.google.com/apis/library/calendar-json.googleapis.com)
   - Required for reading calendar events (used for calendar-aware AI replies and the Calendar view).

3. **Google People API** (optional but recommended)
   - [Enable People API](https://console.cloud.google.com/apis/library/people.googleapis.com)
   - Used for retrieving user profile information during OAuth. The `userinfo.email` and `userinfo.profile` scopes work without this API enabled in most cases, but enabling it avoids occasional issues.

## Step 3: Configure the OAuth Consent Screen

Before creating credentials, you need to configure the consent screen that users see when authorizing the app.

1. Navigate to **APIs & Services > OAuth consent screen**.
2. Select **External** as the user type (unless you have a Google Workspace organization and want to restrict access to internal users only). Click **Create**.
3. Fill in the required fields:

   | Field | Value |
   | --- | --- |
   | **App name** | Whatever you want users to see (e.g. "Mail Client") |
   | **User support email** | Your email address |
   | **Developer contact email** | Your email address |

4. Click **Save and Continue** to move to the **Scopes** step.

### Adding Scopes

1. Click **Add or Remove Scopes**.
2. In the filter box, search for and select each of these scopes:

   | Scope | Description |
   | --- | --- |
   | `openid` | Basic authentication |
   | `.../auth/userinfo.email` | View your email address |
   | `.../auth/userinfo.profile` | View your basic profile info |
   | `.../auth/gmail.readonly` | View your email messages and settings |
   | `.../auth/gmail.send` | Send email on your behalf |
   | `.../auth/gmail.modify` | View and modify (but not delete) your email |
   | `.../auth/gmail.labels` | Manage your email labels |
   | `.../auth/calendar.readonly` | View your calendars and events |

   > **Tip:** You can paste the full scope URLs into the "Manually add scopes" box at the bottom:
   > ```
   > openid
   > https://www.googleapis.com/auth/userinfo.email
   > https://www.googleapis.com/auth/userinfo.profile
   > https://www.googleapis.com/auth/gmail.readonly
   > https://www.googleapis.com/auth/gmail.send
   > https://www.googleapis.com/auth/gmail.modify
   > https://www.googleapis.com/auth/gmail.labels
   > https://www.googleapis.com/auth/calendar.readonly
   > ```

3. Click **Update** to save the scopes, then **Save and Continue**.

### Test Users

While your app is in **Testing** status (before verification), only test users you explicitly add can authorize the app.

1. On the **Test users** step, click **Add Users**.
2. Add the Gmail addresses of anyone who will use the app.
3. Click **Save and Continue**, then **Back to Dashboard**.

> **Note:** You can add up to 100 test users. If you need more, you will need to submit the app for Google verification (see [Publishing Your App](#publishing-your-app-optional) below).

## Step 4: Create OAuth 2.0 Credentials

1. Navigate to **APIs & Services > Credentials**.
2. Click **Create Credentials > OAuth client ID**.
3. Select **Web application** as the application type.
4. Give it a name (e.g. "Mail Client Web").

### Authorized Redirect URIs

You need to add **two** redirect URIs -- one for user login and one for connecting Gmail accounts:

| URI | Purpose |
| --- | --- |
| `https://yourdomain.com/api/auth/google/callback` | User login via Google |
| `https://yourdomain.com/api/accounts/oauth/callback` | Connecting a Gmail account |

Replace `yourdomain.com` with your actual domain name.

> **For local development**, add these as well:
> ```
> http://localhost:8080/api/auth/google/callback
> http://localhost:8080/api/accounts/oauth/callback
> ```

5. Click **Create**.
6. Google will show you the **Client ID** and **Client Secret**. Copy both values -- you will need them for the `.env` file.

## Step 5: Configure the Application

Add the credentials to your `.env` file in the project root:

```bash
GOOGLE_CLIENT_ID=123456789-abcdefg.apps.googleusercontent.com
GOOGLE_CLIENT_SECRET=GOCSPX-your-secret-here
GOOGLE_REDIRECT_URI=https://yourdomain.com/api/auth/google/callback
```

The `GOOGLE_REDIRECT_URI` should match the **login** callback URI you registered above. The account-connection callback URI is derived automatically from `ALLOWED_ORIGINS`.

After updating the `.env` file, restart the backend:

```bash
bash scripts/restart.sh --backend
```

## Step 6: Verify Everything Works

1. Open your mail client in the browser and click **Sign in with Google**.
2. You should see the Google consent screen with your app name and the requested permissions.
3. After approving, you will be redirected back and logged in.
4. Go to **Settings > Accounts** and click **Connect Gmail Account** to link a mailbox.
5. This will show a second consent screen requesting the full Gmail and Calendar scopes.
6. Once connected, the app will begin syncing your email in the background.

## Scope Reference

Here is a complete list of every OAuth scope the application requests and why:

| Scope | When Requested | Why |
| --- | --- | --- |
| `openid` | Login + account connect | Required for OpenID Connect authentication |
| `userinfo.email` | Login + account connect | Identifies the user by email address |
| `userinfo.profile` | Login + account connect | Retrieves display name and profile picture |
| `gmail.readonly` | Account connect | Read email messages, threads, and metadata |
| `gmail.send` | Account connect | Send and reply to emails |
| `gmail.modify` | Account connect | Mark as read/unread, star, archive, move to trash/spam, apply labels |
| `gmail.labels` | Account connect | List, create, and manage Gmail labels |
| `calendar.readonly` | Account connect | Read calendar events for calendar-aware AI replies and the Calendar page |

> **Privacy note:** The app never requests `gmail.compose` (full compose access) or any write access to your calendar. Email send is handled through the more limited `gmail.send` scope, and calendar access is read-only.

## Troubleshooting

### "Access blocked: This app's request is invalid"

This usually means the redirect URI in the OAuth request does not match any URI registered in Google Cloud Console. Double-check that both callback URIs are listed exactly as shown in [Step 4](#step-4-create-oauth-20-credentials), including the protocol (`https://`) and path.

### "This app isn't verified"

This is normal when your app is in **Testing** status. Click **Continue** (you may need to click "Advanced" first) to proceed. Only test users you added in [Step 3](#test-users) can get past this screen.

### "Error 403: access_not_configured"

The required API is not enabled in your Google Cloud project. Go back to [Step 2](#step-2-enable-the-required-apis) and make sure all three APIs are enabled.

### Calendar not syncing

If email works but the calendar page shows no events, the account may have been connected before the `calendar.readonly` scope was added. Go to **Settings > Accounts**, find the account, and click **Reauthorize** to grant the calendar scope.

### "OAUTHLIB_RELAX_TOKEN_SCOPE" warning

Google sometimes returns additional scopes (like `openid`) beyond what was requested. The app sets the `OAUTHLIB_RELAX_TOKEN_SCOPE=1` environment variable to handle this gracefully. This is already configured in the systemd service files.

## Publishing Your App (Optional)

While in **Testing** mode, only the test users you added can use the app. If you want to allow any Google account to connect:

1. Go to **APIs & Services > OAuth consent screen**.
2. Click **Publish App**.
3. Because the app requests sensitive Gmail scopes, Google will require a **verification review**. This process involves:
   - Demonstrating that you comply with the [Google API Services User Data Policy](https://developers.google.com/terms/api-services-user-data-policy)
   - Providing a privacy policy URL
   - Possibly undergoing a third-party security assessment

For a self-hosted personal mail client, **Testing** mode with your own email as a test user is usually sufficient. You do not need to publish or verify the app.
