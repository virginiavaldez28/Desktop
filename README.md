# Gestión Financiera — Grupo Valpob S.R.L.

Aplicación web que reemplaza a la planilla `Valpob_Punto_Equilibrio_Rentabilidad.xlsx`.

- El equipo carga los datos del mes en formularios: **Personal y Nómina**, **Registro de Compras**, **Registro de Ventas** y **Apertura de gastos** (alquileres, seguros, leasing, gastos bancarios, etc.).
- Las facturas de venta y de compra guardan el **neto** y el **IVA** por separado. Todos los reportes de rentabilidad usan el neto (sin IVA); el Estado de Resultados muestra el IVA aparte, como dato informativo (débito, crédito y saldo).
- La aplicación calcula sola los 5 reportes: **Estado de Resultados**, **Apertura de Costos y Gastos**, **Costos por Servicio**, **Punto de Equilibrio** y **Rentabilidad por Servicio**. Los reportes funcionan para cualquier mes o rango de meses, sin límite de años, y el Estado de Resultados permite comparar dos períodos.
- Cualquier reporte se descarga en **Excel** o **PDF**.
- Cada renglón guarda quién lo cargó y quién lo modificó por última vez. El historial completo de cambios está en el botón **Historia** de cada registro.

---

## 1. Cómo se usa, mes a mes

1. **Abrir el mes.** En *Carga de datos → Períodos (meses) → Agregar* se carga el año y el mes. Mientras un mes no existe, no aparece en los desplegables.
2. **Cargar la nómina.** Para no empezar de cero, en *Períodos (meses)* se tilda el mes nuevo y se elige la acción **"Copiar la nómina del mes anterior"**. Eso copia a todas las personas activas con su servicio y su %, con los importes en 0. Después se completan los importes de cada una.
3. **Cargar compras, ventas y gastos.** Cada factura va en un renglón. Las notas de crédito se cargan en negativo. Los montos se escriben en formato argentino: `1.234.567,89`.
4. **Revisar los reportes.** Arriba de cada reporte se elige *Desde* y *Hasta*. En Costos por Servicio, Punto de Equilibrio y Rentabilidad, si el rango es de un solo mes se ve ese mes; si es más largo, se ve el acumulado.
5. **Cerrar el mes** cuando esté revisado: en *Períodos (meses)* se tilda el mes y se elige **"Cerrar los meses elegidos"**. Un mes cerrado ya no lo puede modificar nadie, salvo un Administrador.

**% de asignación manual.** En el mes (*Períodos*) se cambia *% de asignación de costos fijos* a **Manual**, se completan los % de los 9 servicios (tienen que sumar 100) y se guarda. Para volver al criterio por ventas, se pone de nuevo **Automático**.

### Roles

| Rol | Qué puede hacer |
|---|---|
| **Administrador** | Todo: cargar, ver reportes, manejar usuarios, abrir y cerrar meses, cargar la Apertura de gastos. |
| **Carga de Personal** | Personas y Personal y Nómina. |
| **Carga de Compras** | Proveedores y Registro de Compras. |
| **Carga de Ventas** | Clientes y Registro de Ventas. |
| **Solo lectura** | Ve los reportes y los registros, pero no puede cargar ni modificar nada. |

Para crear un usuario: *Carga de datos → Usuarios → Agregar*, y en **Grupos** se le asigna el rol. Una persona puede tener más de un rol (por ejemplo "Carga de Compras" + "Solo lectura" para que también vea los reportes).

---

## 2. Reglas de cálculo (iguales a las del Excel)

1. **Compras GENERAL.** Se reparten entre los 9 servicios con el % de asignación del mes.
   - **EPP** (mamelucos, calzado, etc.): se carga con Categoría *Materiales e Insumos* y Servicio Asignado *GENERAL (a prorratear por personal afectado)*. Se reparte según la cantidad de personal de cada servicio en el mes, tomada de Personal y Nómina: una persona al 50% cuenta 0,5, Administración no cuenta, y el Pool Operativo se reparte entre sus 7 servicios según las ventas, igual que su costo.
2. **Gastos operativos en Compras.** Las facturas con categoría *Otros Egresos* o *Gasto Operativo — Servicios / Seguros / Alquileres / Impuestos y Tasas* no entran a Costos por Servicio: van directo a su renglón de Gastos Operativos del Estado de Resultados (Otros Egresos va a *Otros Gastos Operativos*).
3. **% de asignación.** En modo Automático es Ventas del servicio ÷ Ventas totales del mes; en modo Manual, el % cargado. Se usa para las compras GENERAL y para repartir los costos fijos.
4. **Mano de obra.**
   - Soporte a Producción PAE y Cercos suman su cuadrilla fija.
   - El **Pool Operativo** se reparte entre los otros 7 servicios en proporción a sus ventas del mes.
   - **Administración** es gasto operativo: entra a los costos fijos y se reparte con el % de asignación.
5. **Costos fijos** = Total Gastos Operativos + Total Gastos Bancarios del mes.
6. **Punto de equilibrio** = Costos Fijos ÷ Margen de Contribución %.

### Diferencia con el Excel (a propósito)

En el Excel, la fórmula de Mano de Obra Directa de *Costos por Servicio* (fila 10) sólo suma al personal asignado directo a Soporte PAE y a Cercos. Las personas asignadas directo a otro servicio sí se suman en el Estado de Resultados, pero no aparecen en Costos por Servicio. Con los datos de Julio 2026 son:

- Castro (Hidrolavadoras): $ 5.279.525,52
- Benedetti (Módulos): $ 5.822.617,83
- Pistan (Obras Civiles): $ 3.310.422,03

Por eso, en el Excel la suma del Resultado Neto por Servicio ($ 116.755.016,54) no coincide con el Resultado Operativo del Estado de Resultados ($ 102.342.451,16). Los comentarios de esas celdas del Excel ("Hidrolavadoras: Castro Sandro (base) + parte proporcional del pool") muestran que la idea era sumarlos. La aplicación los suma a su servicio, así los dos reportes cierran entre sí.

### Verificación contra el Excel

```
python manage.py comparar_excel Valpob_Punto_Equilibrio_Rentabilidad.xlsx
```

Compara 250 celdas: todo el Estado de Resultados de Julio y Agosto 2026, y Costos por Servicio, Punto de Equilibrio y Rentabilidad del mes elegido en el Excel. Las tres últimas hojas se calculan con el mismo criterio de mano de obra que la fórmula del Excel, para probar que las fórmulas son idénticas. Al final muestra el efecto de la diferencia explicada arriba.

---

## 3. Probar la aplicación en una computadora (sin servidor)

Hace falta Python 3.11 o más nuevo.

```
pip install -r requirements.txt
python manage.py migrate
python manage.py createsuperuser        # usuario y contraseña de Administrador
python manage.py importar_excel Valpob_Punto_Equilibrio_Rentabilidad.xlsx
python manage.py runserver
```

Después se entra con el navegador a <http://localhost:8000>. Los datos quedan en el archivo `db.sqlite3`.

---

## 4. Instalación en un servidor (producción)

Se recomienda un servidor chico en la nube: cualquier VPS Linux con 1 GB de RAM alcanza (DigitalOcean, Hetzner, Contabo, Donweb, etc.). También sirve una PC de la oficina encendida todo el día. Hace falta tener instalado **Docker**.

```
git clone <dirección del repositorio> valpob
cd valpob
cp .env.example .env
nano .env                                   # completar SECRET_KEY, DB_PASSWORD, ALLOWED_HOSTS, etc.
docker compose up -d --build                # arranca la base de datos y la aplicación
docker compose exec web python manage.py createsuperuser
```

**Carga inicial desde el Excel** (una sola vez):

```
docker compose cp Valpob_Punto_Equilibrio_Rentabilidad.xlsx web:/tmp/valpob.xlsx
docker compose exec web python manage.py importar_excel /tmp/valpob.xlsx --usuario <tu usuario>
```

Después se completan el neto y el IVA de cada factura de venta con los listados del sistema de facturación (el Excel tenía un solo importe por factura):

```
docker compose cp Julio_ventas.xlsx web:/tmp/Julio_ventas.xlsx
docker compose cp agosto_ventas.xlsx web:/tmp/agosto_ventas.xlsx
docker compose exec web python manage.py completar_iva_ventas /tmp/Julio_ventas.xlsx /tmp/agosto_ventas.xlsx --usuario <tu usuario>
```

Las compras de un mes se cargan desde la planilla de revisión (la que tiene las columnas "Categoría final" y "Servicio Asignado final"):

```
docker compose cp Compras_Julio_2026_final.xlsx web:/tmp/compras.xlsx
docker compose exec web python manage.py importar_compras /tmp/compras.xlsx --anio 2026 --mes 7 --usuario <tu usuario>
```

El paso de ventas corrige además la Factura B N° 3-22 de Agosto (Ministerio de Infraestructura): en el Excel figuraba con el IVA incluido ($ 1.428.830,92) y su neto es $ 1.180.852,00.

La carga inicial importa:

- Personal y Nómina.
- Las facturas reales de venta de Julio y Agosto.
- Los ítems reales de Apertura (Impuesto de Sellos, SIRCREB, Leasing, Planes de Pago).
- Los Gastos Bancarios y el Saldo de Proveedores.

Los renglones marcados *"Ejemplo (reemplazar)"* se omiten: las 4 facturas de compra de ejemplo, y los ejemplos de Alquileres, Servicios, Seguros y Otros Gastos Operativos. Si se quieren incluir, se agrega `--incluir-ejemplos`.

### HTTPS (candado del navegador)

Si la aplicación va a estar en internet, tiene que usarse con HTTPS. La forma más simple es instalar [Caddy](https://caddyserver.com/docs/install) en el servidor, que consigue el certificado solo. Se pone en `/etc/caddy/Caddyfile`:

```
gestion.valpob.com.ar {
    reverse_proxy localhost:8000
}
```

y después se corre `sudo systemctl reload caddy`. El dominio tiene que apuntar a la IP del servidor.

### Actualizar a una versión nueva

```
cd valpob
./scripts/backup.sh                         # siempre, antes de actualizar
git pull
docker compose up -d --build                # aplica solo los cambios de la base de datos
```

### Copias de seguridad

- `./scripts/backup.sh` guarda una copia en la carpeta `backups/`.
- Conviene programarla todos los días con `crontab -e`:

  ```
  0 23 * * * /ruta/a/valpob/scripts/backup.sh
  ```

- Las copias hay que llevarlas también fuera del servidor (Google Drive, disco externo).
- Para restaurar una copia: `./scripts/restaurar.sh backups/<archivo>.sql.gz`. **Reemplaza todos los datos actuales.**

---

## 5. Para quien mantenga el código

- **Stack.** Django 5.2 + PostgreSQL. Las pantallas de carga usan el admin de Django. El historial de cambios usa django-simple-history. Las exportaciones usan openpyxl (Excel) y reportlab (PDF).
- **Archivos principales:**
  - `gestion/catalogos.py`: los 9 servicios, las categorías y los rubros. Son listas cerradas.
  - `gestion/models.py`: tablas de carga y validaciones.
  - `gestion/calculos.py`: **motor de cálculo**, con todas las reglas. No usa la base de datos, así se prueba aislado.
  - `gestion/reportes.py`: arma los 5 reportes como tablas. La misma tabla sale en pantalla, en Excel y en PDF.
  - `gestion/admin.py`: pantallas de carga, cierre de mes y auditoría.
  - `gestion/roles.py`: los roles y sus permisos. Se actualizan solos con `migrate`.
  - `gestion/excel.py`, `gestion/importacion.py` y `gestion/verificacion.py`: lectura del Excel, carga inicial y comparación.
- **Tests.**
  - `python manage.py test gestion` corre todos los tests.
  - Para incluir la comparación contra el Excel real: `VALPOB_EXCEL=/ruta/al/excel.xlsx python manage.py test gestion`.
- **El Excel original no se sube al repositorio**, porque tiene sueldos y CUIL. Por eso está en `.gitignore`.
