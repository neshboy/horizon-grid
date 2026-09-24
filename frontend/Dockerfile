FROM node:20-alpine

WORKDIR /app

# WORKDIR creates /app while still root (the default user at this point),
# so it must be explicitly chowned before switching to the non-root `node`
# user below -- otherwise `npm install` fails with EACCES trying to create
# node_modules inside a root-owned directory.
RUN chown node:node /app

# --chown=node:node (not a separate `RUN chown -R`, which is slower on a
# large tree and adds its own layer) so node_modules and the app source are
# owned by the non-root `node` user the base image already provides, before
# switching to it below -- was previously running the dev server as root
# with no USER directive at all.
COPY --chown=node:node package.json package-lock.json* ./
USER node
RUN npm install

COPY --chown=node:node . .

# docker-compose.yml mounts an anonymous volume over /app/.next so the dev
# server's build cache survives independently of the ./frontend bind mount.
# That path doesn't exist yet at this point in the image (Next.js only
# creates it at runtime), so Docker would otherwise initialize the volume
# root-owned -- causing "EACCES: permission denied, open
# '/app/.next/package.json'" for the non-root `node` user at container
# start. Pre-creating it now, chowned, means the volume is seeded from an
# already-correctly-owned directory.
RUN mkdir -p .next && chown node:node .next

EXPOSE 3000

CMD ["npm", "run", "dev"]
