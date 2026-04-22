# htmlDashboard — Dashboard HTML Standalone *(en desarrollo)*

Dashboard de telemetría en tiempo real sin necesidad de Docker, Grafana ni instalación de dependencias. Se abre directamente en el navegador.

## Objetivo

Complementar el stack local (Grafana) con una vista de baja latencia para usar en competencia. Grafana introduce ~1-2s de delay; este dashboard conecta directo vía **WebSocket MQTT (HiveMQ)** para mostrar los datos prácticamente en tiempo real.

## Plan

- Un solo archivo `index.html` + assets mínimos
- Conexión WebSocket al broker HiveMQ (mismas credenciales que `liveDashboard/.env`)
- Paneles: RPM, velocidad, temperatura motor, temperatura CVT, batería, vueltas, mapa GPS
- Sin frameworks pesados — HTML/CSS/JS vanilla o librería ligera

## Uso previsto

```
Laptop en pits (con internet)
  → Abrir index.html en el navegador
  → Se conecta a HiveMQ via WebSocket
  → Muestra telemetría en vivo
```

## Estado

Pendiente de implementación. La estructura del proyecto y la integración con HiveMQ están definidas en `liveDashboard/`.
