FROM node:20-alpine

WORKDIR /app

# Copy package files
COPY package*.json ./

# Install dependencies
RUN npm config set registry https://registry.npmmirror.com && \
    npm install

# Copy application code
COPY . .

# Expose port
EXPOSE 3000

# Copy startup script
COPY start.sh /start.sh
RUN chmod +x /start.sh

# Run development server with dependency check
CMD ["/start.sh"]
