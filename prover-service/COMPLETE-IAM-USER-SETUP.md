# Complete IAM User Setup - Create Access Keys

You've created the IAM user! Now let's create access keys for CLI.

## Current Status ✅
- User created: `Julian`
- Console access: Configured
- Next: Create CLI access keys

## Step 1: Go to Security Credentials

Since you're on the user details page:

1. Look for tabs at the top:
   - **"Permisos"** (Permissions)
   - **"Grupos"** (Groups)
   - **"Etiquetas"** (Tags)
   - **"Credenciales de seguridad"** (Security credentials) ← Click this!

## Step 2: Create Access Keys

In the "Credenciales de seguridad" tab:

1. Scroll down to **"Claves de acceso"** (Access keys) section
2. Click **"Crear clave de acceso"** (Create access key)
3. Select use case:
   - **"Interfaz de línea de comandos (CLI)"** ← Select this
4. Check the confirmation box
5. Click **"Siguiente"** (Next)
6. Optional: Add description tag (e.g., "zkLogin EC2 deployment")
7. Click **"Crear clave de acceso"** (Create access key)

## Step 3: Save Your Credentials! ⚠️

**IMPORTANT**: This is your ONLY chance to see the secret key!

1. You'll see:
   - **Access key ID**: Something like `AKIAIOSFODNN7EXAMPLE`
   - **Secret access key**: Something like `wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY`

2. Either:
   - Click **"Descargar archivo .csv"** (Download .csv file) - RECOMMENDED
   - Or copy both values to a secure location

3. Click **"Listo"** (Done)

## Step 4: Add Permissions

If you haven't added permissions yet:

1. Go to **"Permisos"** (Permissions) tab
2. Click **"Añadir permisos"** → **"Adjuntar políticas directamente"**
3. Search and select:
   - `AmazonEC2FullAccess`
   - `IAMReadOnlyAccess`
4. Click **"Siguiente"** → **"Añadir permisos"**

## Step 5: Configure AWS CLI

On your local machine:

```bash
aws configure --profile confio
```

Enter:
- **AWS Access Key ID**: [from step 3]
- **AWS Secret Access Key**: [from step 3]
- **Default region name**: eu-central-2
- **Default output format**: json

## Step 6: Test Configuration

```bash
# Test the credentials
aws sts get-caller-identity --profile confio

# You should see:
{
    "UserId": "AIDAXXXXXXXXX",
    "Account": "201615375650",
    "Arn": "arn:aws:iam::201615375650:user/Julian"
}
```

## Step 7: Launch EC2!

```bash
# Set the profile
export AWS_PROFILE=confio

# Create IAM role (optional but recommended)
./setup-ec2-iam-role.sh

# Launch the EC2 instance
./launch-ec2-spot.sh
```

## 🔒 Security Checklist

- [ ] Downloaded/saved access keys securely
- [ ] Added EC2 permissions to user
- [ ] Configured AWS CLI with profile
- [ ] Tested credentials work
- [ ] Ready to launch EC2!

## ⚠️ Important Notes

1. **Never share** your secret access key
2. **Never commit** credentials to git
3. **Delete keys** after setting up EC2 (use IAM roles instead)
4. Consider enabling **MFA** on this IAM user