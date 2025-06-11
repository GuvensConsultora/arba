# Módulo Odoo: ARBA - Exportación de Impuestos

Este módulo agrega una funcionalidad para generar y descargar archivos CSV con los datos del modelo `account.tax`, integrados dentro de un menú personalizado en Odoo.

## 🔧 Funcionalidades

- Exportación de todos los impuestos (`account.tax`) en formato CSV.
- Visualización y descarga del archivo desde la interfaz de Odoo.
- Integración con el sistema de permisos de usuarios.
- Menú independiente bajo "ARBA" para facilitar el acceso.

## 🗂️ Estructura del módulo

- **Modelo:** `arba.exportperc`
- **Vista:** Formulario con botón para generar el archivo CSV.
- **Acción:** Abre el formulario para iniciar la exportación.
- **Menú:** Bajo un menú raíz `ARBA`.

## 📂 Archivos importantes

- `arba.py`: contiene la lógica del modelo y la generación del CSV.
- `exportcsv.xml`: vista del formulario y configuración del menú.
- `__manifest__.py`: define el módulo e incluye los archivos necesarios.
- `ir.model.access.csv`: permisos de acceso al modelo `arba.exportperc`.

## ✅ Instalación

1. Copiar el módulo dentro del directorio de addons.
2. Asegurarse de que el archivo `exportcsv.xml` está listado en `__manifest__.py`.
3. Instalar o actualizar el módulo desde Odoo o ejecutar:
   ```bash
   ./odoo-bin -u arba
````

## 🚀 Uso

1. Ir al menú **ARBA > Exportar CSV Impuestos**.
2. Ingresar un nombre de archivo.
3. Hacer clic en **Generar CSV**.
4. Descargar el archivo generado desde el mismo formulario.

## 🔐 Permisos

El modelo `arba.exportperc` requiere permisos para que los usuarios puedan acceder y ejecutar la exportación. Ver `ir.model.access.csv`.

## 🧑‍💻 Autor

* **Tu Nombre**
* [https://tusitio.com](https://tusitio.com)

## 📜 Licencia

LGPL-3

```

---
