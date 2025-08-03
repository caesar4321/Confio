# How to Navigate to IAM Users in AWS Console

## You're currently in: Security Credentials (Root Account)
## You need to go to: IAM Service

### Step 1: Go to IAM Service

**Option A - Direct Link:**
👉 Click here: https://console.aws.amazon.com/iam/home#/users

**Option B - Navigate from Console:**
1. Click **"Services"** (top left menu) or use the search bar
2. Type **"IAM"**
3. Click **"IAM"** (Identity and Access Management)

### Step 2: Once in IAM Dashboard

You'll see a left sidebar with:
- Dashboard
- User groups
- **Users** ← Click this!
- Roles
- Policies
- Identity providers
- Account settings

### Step 3: Create User

1. Click **"Users"** in the left sidebar
2. Click orange button **"Create user"** (top right)
3. User name: `confio-deployer`

### Visual Guide:

```
AWS Console Home
  ↓
Services → IAM
  ↓
IAM Dashboard
  ↓
Left Menu → Users
  ↓
Create user button
```

## 🎯 Quick Solution:

1. **Open new tab**: https://console.aws.amazon.com/iam/
2. You'll see the IAM dashboard
3. Click **"Users"** in the left menu
4. Click **"Create user"**

## 📸 What you should see:

The IAM Users page will show:
- A list of existing users (might be empty)
- Orange/Yellow **"Create user"** button
- Options to manage users

## ⚠️ Make sure:
- You're in the correct AWS region (though IAM is global)
- You're logged in as root user (to create the first IAM user)
- You see "IAM" in the page title, not "Security credentials"