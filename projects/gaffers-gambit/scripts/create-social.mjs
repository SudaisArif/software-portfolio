import sharp from "sharp";
import { writeFile } from "node:fs/promises";
const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="630" viewBox="0 0 1200 630">
<rect width="1200" height="630" fill="#152c23"/>
<rect x="30" y="30" width="1140" height="570" rx="4" fill="none" stroke="#53694f"/>
<text x="70" y="92" fill="#efa67d" font-size="17" letter-spacing="3" font-family="monospace">THE DAILY FOOTBALL RARITY GAME</text>
<text x="65" y="209" fill="#f1edda" font-size="78" font-family="Georgia,serif">Gaffer’s Gambit</text>
<text x="70" y="298" fill="#efa67d" font-size="53" font-style="italic" font-family="Georgia,serif">Think you know ball?</text>
<text x="73" y="359" fill="#c8d0bb" font-size="25" font-family="Arial">7 questions. Rarer answers score more.</text>
<path d="M76 493 Q480 358 1030 450" stroke="#d5d6b5" fill="none" stroke-dasharray="7 12" stroke-width="2"/>
<path d="M930 420L957 400H1100V528L1072 549H930Z" fill="#203b2d"/>
<path d="M930 420H1072V549H930Z M1072 420L1100 400 M1072 549L1100 528 M930 420L957 400H1100V528" stroke="#f1edda" stroke-width="4" fill="none"/>
<path d="M958 420V549 M987 420V549 M1015 420V549 M1044 420V549 M930 446H1072 M930 472H1072 M930 498H1072 M930 523H1072" stroke="#72846a" fill="none"/>
<circle cx="1033" cy="440" r="15" fill="#efa67d"/><path d="M1028 431L1038 431L1042 440L1033 446L1024 440Z" fill="#152c23"/>
<text x="73" y="550" fill="#d2d8be" font-size="17" font-family="monospace" letter-spacing="2">FREE TO PLAY. A NEW MATCH EVERY DAY.</text>
</svg>`;
await writeFile("public/social-launch.svg", svg);
await sharp(Buffer.from(svg)).png().toFile("public/social-launch.png");
