# Publicar el gemelo como app para iPhone y Android

Resultado: una dirección web como `https://TU-USUARIO.github.io/clima-tenerife/` que se instala en
el móvil como una app, con icono propio y a pantalla completa. Se actualiza sola cada hora, aunque
tu PC esté apagado. Coste: 0 €. No hace falta instalar nada en el PC.

**Cómo funciona:** GitHub ejecuta cada hora `nube.py`. Ese programa lee los datos ya publicados en
la web, descarga lo nuevo de AEMET y AgroCabildo y vuelve a publicar la app con **las últimas 24 h**.
**No se guarda nada en el repositorio**: no hay commits ni conflictos. El histórico completo lo
lleva el gemelo local del PC.

---

## 1. Crear la cuenta de GitHub (5 min)

1. Entra en <https://github.com/signup> y crea una cuenta gratuita. Tu **nombre de usuario**
   aparecerá en la dirección de la app, así que elígelo con eso en mente.
2. Confirma el correo y, si te lo pide, activa la verificación en dos pasos.

## 2. Crear el repositorio

1. Arriba a la derecha, pulsa **+ → New repository**.
2. En *Repository name* escribe, por ejemplo, `clima-tenerife`.
3. Marca **Public**. Es necesario para que GitHub Pages y Actions sean gratis. Solo se verán el
   código y los datos meteorológicos, que ya son públicos. Tu clave de AEMET queda oculta (paso 4).
4. **No** marques "Add a README". Pulsa **Create repository**.

## 3. Subir los ficheros

1. Descomprime `gemelo_tenerife.zip` en una carpeta nueva.
   ⚠️ **No subas tu carpeta de trabajo local:** contiene `config.ini` con tu clave y la base de
   datos local.
2. En la página del repositorio vacío, pulsa el enlace **uploading an existing file**.
3. Abre la carpeta descomprimida `gemelo_tenerife`, selecciona **todo su contenido** (Ctrl+A),
   incluida la carpeta `.github`, y arrástralo a la ventana del navegador.
4. Abajo, pulsa **Commit changes**.
5. **Comprueba** que en el repositorio aparece la carpeta `.github`. Si no aparece (algunos
   navegadores ignoran las carpetas que empiezan por punto):
   - Pulsa **Add file → Create new file**.
   - En el nombre escribe exactamente `.github/workflows/actualizar.yml`. Al teclear las `/`
     se crean las carpetas.
   - Abre `.github/workflows/actualizar.yml` del zip con el Bloc de notas, copia todo y pégalo.
   - Pulsa **Commit changes**.

## 4. Guardar la clave de AEMET como secreto

1. En el repositorio: **Settings → Secrets and variables → Actions → New repository secret**.
2. *Name*: `AEMET_API_KEY`  ·  *Secret*: tu clave completa (la que empieza por `eyJ…`).
3. **Add secret**. Nadie podrá verla, ni siquiera tú: solo la usa el proceso automático.

## 5. Activar GitHub Pages

**Settings → Pages → Build and deployment → Source: GitHub Actions**. Se guarda automáticamente.

## 6. Primera ejecución

1. Pestaña **Actions**. Si aparece un aviso para habilitar los workflows, acéptalo.
2. A la izquierda elige **Actualizar datos y app** y pulsa **Run workflow**.
3. Pulsa el botón verde **Run workflow**. Tarda unos 2–5 minutos; algo más si pides el
   relleno.
4. Cuando acabe en verde ✅, la dirección de la app aparece dentro de la ejecución, en el paso
   *Publicar la app*. También está en **Settings → Pages**:
   `https://TU-USUARIO.github.io/clima-tenerife/`

A partir de ahí se ejecuta **sola cada hora**, en el minuto 25. GitHub a veces la retrasa unos
minutos.

## 7. Instalar en el móvil

- **iPhone:** abre la dirección en **Safari** → botón **Compartir** (cuadrado con flecha) →
  **Añadir a pantalla de inicio**.
- **Android:** abre la dirección en **Chrome** → menú **⋮** → **Instalar aplicación** (o
  *Añadir a pantalla de inicio*).

Aparecerá el icono **Clima TF**. Al abrirla:
- **Variables:** barra deslizable arriba.
- **☰ Capas:** resumen de la red, capas, fondo y perfil altitudinal.
- **Ficha de estación:** toca una estación para ver sus gráficas y exportar el CSV.
- **Reproducción:** la barra inferior recorre las últimas 72 h.
- **Sin cobertura:** muestra los últimos datos descargados y las teselas de mapa ya vistas.

---

## Si algo falla

| Síntoma | Solución |
|---|---|
| Falla en *Publicar la app* | Revisa el paso 5 (Source: GitHub Actions) |
| La app no muestra estaciones de AEMET | Abre la ejecución en **Actions** → paso *Descargar datos…* y busca la línea `[AEMET]`. Si dice "Falta la API key", revisa el secreto del paso 4 |
| Sale `[AGROCABILDO] ERROR` | La API del Cabildo no respondió desde los servidores de GitHub (están fuera de España). Se reintenta cada hora; si persiste varios días, avísame |
| La app instalada no muestra cambios | Ciérrala del todo y ábrela de nuevo: la nueva versión se aplica al reabrir |

## Mantenimiento

- **Nada que hacer en el día a día.** Cada ejecución verás dos o tres bloques: **actualizar**,
  **publicar** y, en la ejecución de las 03 UTC, **mantener**. Este último pide a GitHub que no
  desactive el workflow programado, cosa que GitHub hace en los repositorios públicos tras 60 días
  sin actividad.
- **Si en «publicar» un intento sale en rojo y otro en verde**, todo ha ido bien: es un fallo
  intermitente de GitHub y el workflow reintenta hasta 4 veces.
- **Si GitHub deja de ejecutar más de 12 h seguidas**, la app tendrá un hueco en los datos de AEMET
  de ese tramo, porque AEMET solo ofrece las últimas ~12 h. AgroCabildo se recupera completo.
- **Más horas en la app**: cambia `HORAS_VISOR = 24` en `nube.py` (72 o 168). Aparecerá el filtro
  de periodo.
- **La carpeta `datos/` del repositorio** es de la versión anterior y ya no se actualiza; puedes
  dejarla o borrarla.
- **Cambiar la clave de AEMET**: solo hay que editar el secreto (paso 4).
- **El gemelo local** (`iniciar_gemelo.bat`) sigue igual, con su histórico completo, y es
  independiente de la versión publicada.
