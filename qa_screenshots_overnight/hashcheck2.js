const crypto = require('crypto');
// EICAR test string, byte-exact (68 bytes when treated as ASCII/latin1)
const eicar = "X5O!P%@AP[4\\PZX54(P^)7CC)7}$EICAR-STANDARD-ANTIVIRUS-TEST-FILE!$H+H*";
console.log('string length (JS chars):', eicar.length);
const buf = Buffer.from(eicar, 'ascii');
console.log('buffer byte length:', buf.length);
const h = crypto.createHash('sha256').update(buf).digest('hex');
console.log('sha256 hex:', h);
console.log('sha256 hex length:', h.length);
for (let i = 0; i < h.length; i++) {
  process.stdout.write(`${i}:${h[i]} `);
}
console.log();
