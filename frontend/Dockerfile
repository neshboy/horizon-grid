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

EXPOSE 3000

CMD ["npm", "run", "dev"]
