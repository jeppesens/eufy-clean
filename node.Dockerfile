# base docker with python, poetry and all base requirements
FROM node:20 as reqs
RUN apt-get update && apt-get install -y curl && rm -rf /var/lib/apt/lists/*
WORKDIR /

# Copy only requirements to cache them in docker layer
WORKDIR /app
COPY package.json package-lock.json /app/

RUN npm install

# dev image with all dependencies (for local development)
FROM reqs AS final_image
WORKDIR /app
COPY . /app
RUN npm run build
CMD node out/app.js

