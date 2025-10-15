🚀 Jenkins → InfluxDB → Grafana
 <h2>📸 Dashboard</h2> 
<div align="center">  
<img width="1826" height="718" alt="Screenshot 2025-09-01 180107" src="https://github.com/user-attachments/assets/3cd8ec1e-7817-4a9d-b5fb-2e512152db64" />
</div>

🎯 What's This?
<p>Transform Jenkins chaos into actionable insights. Two Python scripts scrape build data and pipe it into InfluxDB for stunning Grafana dashboards.</p>

📦 Scripts
<table>
<tr>
<th>Script</th>
<th>Purpose</th>
</tr>
<tr>
<td><code>jenkins_to_influx.py</code></td>
<td>📊 Single Jenkins instance</td>
</tr>
<tr>
<td><code>two_jenkins_to_influx.py</code></td>
<td>🌐 Multiple Jenkins servers + better error handling</td>
</tr>
</table>


📊 What Gets Tracked
<table>
<tr>
<td>✅ Build results (SUCCESS/FAILURE)</td>
<td>⏱️ Build duration</td>
<td>👤 User activity</td>
</tr>
<tr>
<td>🔢 Build numbers</td>
<td>📅 Timestamps</td>
<td>🏷️ Project metadata</td>
</tr>
</table>
