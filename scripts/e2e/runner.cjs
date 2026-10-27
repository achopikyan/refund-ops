const path=require('node:path');
const {spawnSync}=require('node:child_process');
const [script,...args]=process.argv.slice(2);
const result=spawnSync(process.execPath,[path.resolve(__dirname,script),...args],{cwd:path.resolve(__dirname,'../..'),env:{...process.env,NODE_PATH:path.join(__dirname,'node_modules')},stdio:'inherit',windowsHide:true});
process.exit(result.status??1);
