# IAM Users vs Identity Center

AWS está intentando redirigirte a Identity Center (antes SSO), pero para nuestro caso es más simple usar IAM Users tradicionales.

## ¿Qué hacer?

### Opción 1: Continuar con IAM Users (Recomendado para empezar)

1. **Click "Cancelar"** en el popup
2. Deberías ver la página de "Personas" (Users) vacía
3. Busca el botón **"Crear usuario"** o **"Crear persona"**
   - Puede estar en la parte superior derecha
   - O puede aparecer un mensaje con opciones

### Si no ves el botón "Crear persona":

1. Puede que veas un mensaje como:
   - "Recomendamos usar Identity Center"
   - "Migrar a Identity Center"
   
2. Busca una opción que diga:
   - **"Continuar con IAM users"**
   - **"Crear usuario IAM tradicional"**
   - **"No migrar ahora"**

### Opción 2: Si no puedes crear IAM Users

Si AWS te está forzando a usar Identity Center, podemos:

1. **Usar Identity Center** (más complejo pero más moderno)
2. **Crear las credenciales temporalmente** desde CloudShell

## Solución Rápida con CloudShell

Si tienes problemas, usa esta alternativa:

1. Abre **CloudShell** (icono de terminal en la barra superior de AWS)
2. Ejecuta estos comandos:

```bash
# Crear usuario IAM desde CLI
aws iam create-user --user-name confio-deployer

# Adjuntar política
aws iam attach-user-policy \
  --user-name confio-deployer \
  --policy-arn arn:aws:iam::aws:policy/AmazonEC2FullAccess

# Crear access key
aws iam create-access-key --user-name confio-deployer
```

3. Copia las credenciales que aparecen

## ¿Por qué está pasando esto?

AWS está migrando gradualmente de IAM Users a Identity Center porque:
- Identity Center usa credenciales temporales (más seguro)
- Gestión centralizada de usuarios
- Mejor para organizaciones

Pero para un proyecto simple, IAM Users sigue funcionando bien.

## Siguiente paso:

Dime qué ves exactamente en tu pantalla:
1. ¿Puedes ver algún botón para crear usuario IAM?
2. ¿O solo te da la opción de Identity Center?