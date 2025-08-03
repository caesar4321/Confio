# Crear Usuario IAM para Confio (Español)

Estás en el lugar correcto. "Personas" = "Users" en inglés.

## Paso 1: Crear Persona (Usuario IAM)

1. Click en el botón naranja **"Crear persona"**
2. **Nombre de usuario**: `confio-deployer`
3. Click **"Siguiente"**

## Paso 2: Establecer Permisos

Selecciona **"Adjuntar políticas directamente"** y añade estas políticas:

### Para gestión de EC2:
Busca y marca:
- ✅ `AmazonEC2FullAccess`

### Para futuro despliegue de aplicaciones:
- ✅ `AmazonS3FullAccess`
- ✅ `CloudWatchFullAccess`

### O crear política personalizada (más seguro):

1. Click **"Crear política"**
2. Selecciona **"JSON"**
3. Pega este código:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "EC2SpotManagement",
      "Effect": "Allow",
      "Action": [
        "ec2:RunInstances",
        "ec2:TerminateInstances",
        "ec2:DescribeInstances",
        "ec2:DescribeInstanceStatus",
        "ec2:CreateTags",
        "ec2:DescribeTags",
        "ec2:DescribeSecurityGroups",
        "ec2:AuthorizeSecurityGroupIngress",
        "ec2:DescribeImages",
        "ec2:DescribeKeyPairs",
        "ec2:DescribeSubnets",
        "ec2:DescribeVpcs",
        "ec2:RequestSpotInstances",
        "ec2:DescribeSpotInstanceRequests",
        "ec2:CancelSpotInstanceRequests"
      ],
      "Resource": "*",
      "Condition": {
        "StringEquals": {
          "aws:RequestedRegion": "eu-central-2"
        }
      }
    },
    {
      "Sid": "IAMRoleManagement",
      "Effect": "Allow",
      "Action": [
        "iam:CreateRole",
        "iam:CreateInstanceProfile",
        "iam:AddRoleToInstanceProfile",
        "iam:AttachRolePolicy",
        "iam:CreatePolicy",
        "iam:PassRole",
        "iam:GetRole",
        "iam:GetInstanceProfile"
      ],
      "Resource": [
        "arn:aws:iam::*:role/zkLogin-*",
        "arn:aws:iam::*:instance-profile/zkLogin-*",
        "arn:aws:iam::*:policy/zkLogin-*"
      ]
    }
  ]
}
```

4. **Nombre de política**: `ConfioDeploymentPolicy`
5. Click **"Crear política"**
6. Vuelve a la pestaña de crear persona y selecciona la política

## Paso 3: Revisar y Crear

1. Click **"Siguiente"**
2. Revisa la configuración
3. Click **"Crear persona"**

## Paso 4: Crear Claves de Acceso

1. Click en el usuario `confio-deployer` que acabas de crear
2. Ve a la pestaña **"Credenciales de seguridad"**
3. En la sección **"Claves de acceso"**, click **"Crear clave de acceso"**
4. Selecciona **"Interfaz de línea de comandos (CLI)"**
5. Marca la casilla de confirmación
6. Click **"Crear clave de acceso"**
7. **¡IMPORTANTE!** Descarga el archivo CSV o copia las credenciales

## Paso 5: Configurar AWS CLI

En tu terminal:

```bash
aws configure --profile confio
```

Introduce:
- AWS Access Key ID: [del archivo CSV]
- AWS Secret Access Key: [del archivo CSV]
- Default region name: eu-central-2
- Default output format: json

## Paso 6: Verificar

```bash
aws sts get-caller-identity --profile confio
```

## Paso 7: Lanzar EC2

```bash
export AWS_PROFILE=confio
./launch-ec2-spot.sh
```

## 🔐 Recomendaciones de Seguridad

1. **Activa MFA** en este usuario IAM:
   - En IAM → Personas → confio-deployer → Credenciales de seguridad
   - Click "Asignar dispositivo MFA"

2. **Rota las claves** cada 90 días

3. **Elimina las claves** después de configurar EC2

4. **Nunca subas** el archivo CSV a git