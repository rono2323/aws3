# Use official Nginx image
FROM nginx:latest

# Copy only your index.html
COPY index.html /usr/share/nginx/html/

# Expose port 80
EXPOSE 7121

# Start Nginx in foreground
CMD ["nginx", "-g", "daemon off;"]
