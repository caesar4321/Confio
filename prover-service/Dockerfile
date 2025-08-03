FROM node:18-alpine

# Install build dependencies for native modules and curl for health checks
RUN apk add --no-cache python3 make g++ git curl

WORKDIR /app

# Copy package files
COPY package*.json ./

# Install dependencies
RUN npm install

# Copy the rest of the application
COPY . .

# Download zkLogin zkey file during build
RUN node -e "import('./zklogin-prover.js').then(m => m.initializeProver()).catch(e => console.error('Zkey download failed:', e))"

# Expose port
EXPOSE 3001

# Start the application
CMD ["node", "index.js"]