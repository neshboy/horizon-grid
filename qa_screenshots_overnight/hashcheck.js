const crypto = require('crypto');
const eicar = "X5O!P%@AP[4\\PZX54(P^)7CC)7}$EICAR-STANDARD-ANTIVIRUS-TEST-FILE!$H+H*";
console.log(JSON.stringify(eicar));
console.log('len', eicar.length);
const h = crypto.createHash('sha256').update(eicar, 'ascii').digest('hex');
console.log('sha256:', h, h.length);
