{{- define "urumi.name" -}}
{{- default "urumi" .Chart.Name -}}
{{- end -}}

{{- define "urumi.fullname" -}}
{{- if .Values.fullnameOverride -}}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" -}}
{{- else -}}
{{- $name := include "urumi.name" . -}}
{{- if contains $name .Release.Name -}}
{{- .Release.Name | trunc 63 | trimSuffix "-" -}}
{{- else -}}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" -}}
{{- end -}}
{{- end -}}
{{- end -}}

{{- define "urumi.labels" -}}
app.kubernetes.io/name: {{ include "urumi.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
helm.sh/chart: {{ printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" }}
{{- end -}}

{{- define "urumi.component" -}}
{{- $root := index . 0 -}}
{{- $component := index . 1 -}}
{{- printf "%s-%s" (include "urumi.fullname" $root) $component -}}
{{- end -}}

{{- define "urumi.image" -}}
{{- $root := index . 0 -}}
{{- $img := index . 1 -}}
{{- $registry := $root.Values.global.imageRegistry -}}
{{- $tag := $img.tag | default $root.Chart.AppVersion -}}
{{- if $registry -}}
{{- printf "%s/%s:%s" $registry $img.repository $tag -}}
{{- else -}}
{{- printf "%s:%s" $img.repository $tag -}}
{{- end -}}
{{- end -}}

{{- define "urumi.secretName" -}}
{{- if .Values.secrets.existingSecret -}}
{{- .Values.secrets.existingSecret -}}
{{- else -}}
{{- printf "%s-secrets" (include "urumi.fullname" .) -}}
{{- end -}}
{{- end -}}

{{/* Upstream hosts allowed by the gateway SSRF guard (comma separated). */}}
{{- define "urumi.upstreamHosts" -}}
{{- $root := . -}}
{{- $hosts := list -}}
{{- if $root.Values.woocommerceMcp.enabled -}}{{- $hosts = append $hosts (printf "%s-woocommerce-mcp" (include "urumi.fullname" $root)) -}}{{- end -}}
{{- if $root.Values.inventoryMcp.enabled -}}{{- $hosts = append $hosts (printf "%s-inventory-mcp" (include "urumi.fullname" $root)) -}}{{- end -}}
{{- if $root.Values.shippingMcp.enabled -}}{{- $hosts = append $hosts (printf "%s-shipping-mcp" (include "urumi.fullname" $root)) -}}{{- end -}}
{{- $hosts = append $hosts "127.0.0.1" -}}
{{- $hosts = append $hosts "localhost" -}}
{{- range $root.Values.gateway.allowedUpstreamHosts -}}{{- $hosts = append $hosts . -}}{{- end -}}
{{- join "," $hosts -}}
{{- end -}}

{{/* Browser origins allowed by CORS (comma separated). */}}
{{- define "urumi.corsOrigins" -}}
{{- $root := . -}}
{{- $origins := list -}}
{{- if $root.Values.ingress.enabled -}}
{{- $scheme := ternary "https" "http" $root.Values.ingress.tls.enabled -}}
{{- $origins = append $origins (printf "%s://%s" $scheme $root.Values.ingress.host) -}}
{{- end -}}
{{- $origins = append $origins "http://localhost:5173" -}}
{{- $origins = append $origins "http://127.0.0.1:5173" -}}
{{- $origins = append $origins "http://localhost:8080" -}}
{{- range $root.Values.gateway.corsOrigins -}}{{- $origins = append $origins . -}}{{- end -}}
{{- join "," $origins -}}
{{- end -}}

{{/* Async PostgreSQL DSN for the gateway/agent. Uses $(POSTGRES_PASSWORD) env
     interpolation so the password never appears in a rendered manifest. */}}
{{- define "urumi.databaseUrl" -}}
{{- $root := . -}}
{{- if $root.Values.database.url -}}
{{- $root.Values.database.url -}}
{{- else -}}
{{- printf "postgresql+asyncpg://%s:$(POSTGRES_PASSWORD)@%s-postgres:5432/%s" $root.Values.database.auth.username (include "urumi.fullname" $root) $root.Values.database.auth.database -}}
{{- end -}}
{{- end -}}
