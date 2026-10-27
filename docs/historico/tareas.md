## TODO

### Pendientes
- [ ] Reglas de Negocio 
- [ ] Propongo implementar estas 4 cosas en src/asistente_enriquecimiento.py:
  - [ ] Histórico efectivo de registros enriquecidos: leer output/enriquecimiento_log.json, construir un mapa record_id -> últimas modificaciones, excluir o despriorizar registros cambiados recientemente.
  - [ ] Homogeneidad de labels: normalizar nombres para matching (casefold, trim, espacios), evitar propuestas redundantes por variación de mayúsculas/minúsculas, priorizar labels existentes antes de crear nuevos, permitir propuestas de quitar/agregar para consolidar labels inconsistentes.
  - [ ] Modo estrictamente manual: mantener confirmación una por una, incluir más contexto al imprimir la propuesta: nota actual, labels actuales, categoría actual.
  - [ ] Prompt más estricto: pedir explícitamente homogeneidad, no reproponer cambios recientes, no crear labels nuevos si ya existe uno equivalente.
- [ ] Análisis del tiempo total, del avance por periodos (por meses) por cuentas y por categorías. Un análisis bien poderoso.
- [ ] Chat en el dashboard para poder hacer preguntas con respecto a mis registros y a TODO apoyándose en todo el contexto.
- [ ] Histórico de análisis en el dashboard. Coherencia y consistencia en los análisis para que no sean totalmente diferentes siempre, pero tampoco deben de ser iguales, deben de ser insights que aporten y que no sean redundantes. Podría ser que no se hagan análisis nuevos sino hasta que haya una cantidad considerable de nuevos registros determinada para hacer nuevos análisis o un sistema que te parezca mejor para manejar esto. Que sean análisis constructivos y no cambiantes. Que conserven una línea de discurso, objetivos, etc
- [ ] En pro de mejorar los análisis quisiera que fueran autorevisados por la misma IA, el mismo modelo de Gemini para que sea más preciso, más detallado. Algo así como multiagente, que haga una tarea a la vez aportando para el análisis en un par de prompts.
- [ ] Calidad en el enriquecimiento, debe procurar que haya homogeneidad entre los registros. Siempre que se pueda: mejorar las descripciones y los labels. Llevar un histórico de los registros enriquecidos para no hacer modificaciones constantes en los mismos registros.  
- [ ] Homogeneidad en los labels, mayúsculas o minúsculas, labels consistentes entre sí, no redundantes, modificación de las labels ya existentes.
- [ ] Validación Manual de cada cambio, así como con las reglas aprendidas.
- [ ] Nombres de categorías en español
- [ ] Sankey bug
- [ ] el siguiente paso sería agregar fallback de proveedor histórico:
  - [ ] primero Frankfurter
  - [ ] luego exchangerate.host o similar
  - [ ] y como último recurso usar tasa actual
- [ ] Patrimonio por cuenta y moneda en el tiempo
  - [ ] evolución de balances de cuentas
  - [ ] COP vs USD
  - [ ] equivalente COP
- [ ] Top contrapartes / comercios
  - [ ] quién recibe más dinero
  - [ ] dónde gastas más
  - [ ] ideal para decisiones de ahorro

### Completados
- [x] Soporte para cuentas en USD
- [x] Gráfico de Diagrama de Sankey en el dashboard y demás gráficos interesantes. 
- [x] En las etiquetas obsoletas detectadas en el dashboard se observan repetidas: 🗑️ Basura
    🗑️ Cello
    🗑️ Didi
    🗑️ Basura
    🗑️ familia
    🗑️ Fran
    🗑️ inDrive
    🗑️ Uber
    🗑️ Basura
    🗑️ Didi
    🗑️ familia
    🗑️ Fran
    🗑️ inDrive
    🗑️ Uber
- [x] Soporte para Visualizar las labels en español en todo el sistema, así se sigan manejando en inglés internamente.