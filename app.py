import streamlit as st
import folium
from streamlit_folium import st_folium
from geopy.distance import geodesic
from geopy.geocoders import Nominatim
from geopy.exc import GeocoderTimedOut
import uuid
import json
import os
import math
import random
import re
from fpdf import FPDF
import tempfile

# --- CONFIGURAÇÃO E CONSTANTES ---
st.set_page_config(page_title="AI Travel Planner", layout="wide", page_icon="🧠")

DATA_FILE = "travel_data.json"
WALKING_SPEED_KMH = 5.0
DRIVING_SPEED_KMH = 35.0 
TOLERANCIA_MINUTOS = 30 
ADMIN_PASSWORD = "EuTenhoPermissao031#" 

# Configuração Visual dos Tipos
TYPE_CONFIG = {
    'hotel': {'label': 'Hotel', 'color': 'black', 'icon': 'home', 'fa': 'fa-home'},
    'visit': {'label': 'Visita (Padrão)', 'color': 'blue', 'icon': 'camera', 'fa': 'fa-camera'},
    'food': {'label': 'Restaurante', 'color': 'red', 'icon': 'cutlery', 'fa': 'fa-cutlery'},
    'transport': {'label': 'Transporte', 'color': 'gray', 'icon': 'plane', 'fa': 'fa-plane'}
}

# --- FUNÇÕES UTILITÁRIAS ---

def parse_coordinate(coord_input):
    """Converte inputs variados (DMS string ou Float string) para Float Decimal."""
    coord_str = str(coord_input).strip()
    try:
        return float(coord_str)
    except ValueError:
        pass
    
    regex = r"(\d+)[°º\s]+(\d+)['\s]+([\d.]+)[\"\s]*([NSEWnsew])?"
    match = re.search(regex, coord_str)
    
    if match:
        deg, min, sec, direction = match.groups()
        decimal = float(deg) + (float(min) / 60) + (float(sec) / 3600)
        if direction and direction.upper() in ['S', 'W']:
            decimal *= -1
        return round(decimal, 6)
    return None

def search_place_nominatim(query):
    """Pesquisa local usando OpenStreetMap (Gratuito)."""
    try:
        geolocator = Nominatim(user_agent="travel_architect_ai_app_final_v7_manual")
        location = geolocator.geocode(query, timeout=10)
        if location:
            return location.latitude, location.longitude, location.address
        return None, None, None
    except (GeocoderTimedOut, Exception) as e:
        return None, None, str(e)

def load_data():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            try: return json.load(f)
            except json.JSONDecodeError: return {}
    return {}

def save_data():
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(st.session_state['cities'], f, indent=4, ensure_ascii=False)

# --- GERADOR DE PDF ---

class PDFReport(FPDF):
    def header(self):
        self.set_font('Arial', 'B', 15)
        self.cell(0, 10, 'Roteiro de Viagem - AI Planner', 0, 1, 'C')
        self.ln(10)

    def footer(self):
        self.set_y(-15)
        self.set_font('Arial', 'I', 8)
        self.cell(0, 10, f'Pagina {self.page_no()}', 0, 0, 'C')

def clean_text(text):
    """
    Remove caracteres que não são suportados pelo padrão Latin-1 (como emojis).
    """
    if not text: return ""
    return str(text).encode('latin-1', 'ignore').decode('latin-1')


def generate_pdf(city, map_images):
    """
    Gera o PDF.
    map_images: Dicionário { dia_int: uploaded_file_object }
    """
    pdf = PDFReport()
    pdf.set_auto_page_break(auto=True, margin=15)
    
    # Capa
    pdf.add_page()
    pdf.set_font('Arial', 'B', 24)
    pdf.cell(0, 20, f"Destino: {clean_text(city['name'])}", 0, 1, 'C')
    
    # Dados Gerais
    visit_pois = [p for p in city['pois'] if p.get('day', 0) > 0 and p.get('type') == 'visit']
    days = sorted(list(set(p['day'] for p in visit_pois)))
    hotel = next((p for p in city['pois'] if p.get('type') == 'hotel'), None)

    # --- LOOP POR DIAS ---
    for day in days:
        pdf.add_page()
        pdf.set_font('Arial', 'B', 16)
        pdf.set_fill_color(200, 220, 255)
        pdf.cell(0, 10, f"Dia {day}", 0, 1, 'L', fill=True)
        pdf.ln(5)

        # 1. INSERIR IMAGEM DO MAPA (SE HOUVER UPLOAD)
        if day in map_images and map_images[day] is not None:
            with tempfile.NamedTemporaryFile(delete=False, suffix=".png") as tmp:
                tmp.write(map_images[day].getvalue())
                tmp_path = tmp.name
            
            try:
                pdf.image(tmp_path, x=10, y=None, w=190)
                pdf.ln(5)
            except Exception as e:
                pdf.set_font('Arial', 'I', 10)
                pdf.cell(0, 10, f"Erro na imagem: {str(e)}", 0, 1)
            finally:
                if os.path.exists(tmp_path):
                    os.unlink(tmp_path)
        else:
            pdf.set_font('Arial', 'I', 10)
            pdf.cell(0, 10, "(Sem imagem do mapa carregada para este dia)", 0, 1)

        # 2. TABELA DE ROTEIRO
        day_pois = [p for p in city['pois'] if p.get('day') == day and p.get('type') == 'visit']
        
        route_nodes = []
        if hotel: route_nodes.append(hotel)
        route_nodes.extend(day_pois)
        if hotel: route_nodes.append(hotel)

        pdf.ln(5)
        pdf.set_font('Arial', 'B', 10)
        pdf.cell(10, 8, "#", 1)
        pdf.cell(70, 8, "Local", 1)
        pdf.cell(30, 8, "Duracao", 1) 
        pdf.cell(40, 8, "Deslocamento", 1)
        pdf.cell(30, 8, "Distancia", 1)
        pdf.ln()

        pdf.set_font('Arial', '', 10)
        
        total_km = 0
        total_transit_min = 0
        
        for i in range(len(route_nodes) - 1):
            curr = route_nodes[i]
            next_p = route_nodes[i+1]
            
            dist = geodesic((curr['lat'], curr['lon']), (next_p['lat'], next_p['lon'])).km
            total_km += dist
            
            speed = DRIVING_SPEED_KMH if curr.get('type') == 'hotel' or dist > 2.0 else WALKING_SPEED_KMH
            transit_time = int((dist / speed) * 60)
            total_transit_min += transit_time

            is_return = (i == len(route_nodes) - 2) and next_p.get('type') == 'hotel'
            
            if not is_return:
                label_name = next_p['name']
                duration = f"{next_p.get('time_min', 0)} min"
                
                if next_p.get('type') == 'hotel':
                    label_name = "Retorno ao Hotel"
                    duration = "-"

                pdf.cell(10, 8, str(i+1), 1)
                pdf.cell(70, 8, clean_text(label_name)[:35], 1)
                pdf.cell(30, 8, duration, 1)
                pdf.cell(40, 8, f"{transit_time} min", 1)
                pdf.cell(30, 8, f"{dist:.2f} km", 1)
                pdf.ln()
        
        pdf.ln(5)
        pdf.set_font('Arial', 'B', 11)
        pdf.cell(0, 10, f"Resumo Dia {day}: {total_km:.1f} km percorridos | ~{total_transit_min // 60}h {total_transit_min % 60}m em deslocamentos", 0, 1)

    # --- FOOD SPOTS ---
    # Filtra apenas os restaurantes
    food_spots = [p for p in city['pois'] if p.get('type') == 'food']
    
    # Filtra todas as visitas (para calcular a proximidade)
    all_visits = [p for p in city['pois'] if p.get('type') == 'visit']

    if food_spots:
        pdf.add_page()
        pdf.set_font('Arial', 'B', 16)
        pdf.set_fill_color(255, 200, 200)
        pdf.cell(0, 10, "Restaurantes & Gastronomia", 0, 1, 'L', fill=True)
        pdf.ln(5)
        
        pdf.set_font('Arial', '', 11)
        for f in food_spots:
            # Lógica para encontrar o POI de visita mais próximo
            nearest_name = ""
            min_dist = float('inf') # Infinito positivo

            if all_visits:
                for v in all_visits:
                    # Calcula distância geodésica
                    d = geodesic((f['lat'], f['lon']), (v['lat'], v['lon'])).km
                    if d < min_dist:
                        min_dist = d
                        nearest_name = v['name']
            
            # Formatando o texto
            f_name_clean = clean_text(f['name'])
            
            if nearest_name and min_dist != float('inf'):
                # Ex: "McDonalds - a 0.5 km de Torre Eiffel"
                ref_clean = clean_text(nearest_name)
                line_str = f"{f_name_clean} - a {min_dist:.1f} km de {ref_clean}"
            else:
                line_str = f"{f_name_clean}"

            pdf.set_text_color(200, 0, 0)
            pdf.cell(0, 8, line_str, 0, 1)
            
            pdf.set_text_color(0, 0, 0)
            if f.get('desc'):
                pdf.multi_cell(0, 6, f"   {clean_text(f['desc'])}")
            pdf.ln(2)

    return pdf.output(dest="S").encode("latin-1")


# --- MOTOR DE OTIMIZAÇÃO (SIMULATED ANNEALING) ---

class TravelOptimizer:
    def __init__(self, pois, hotel, max_h_manha, max_h_tarde):
        self.pois = pois
        self.hotel = hotel
        self.max_min_manha = (max_h_manha * 60) + TOLERANCIA_MINUTOS
        self.max_min_tarde = (max_h_tarde * 60) + TOLERANCIA_MINUTOS
        self.dist_matrix = {}
        self._precompute_distances()

    def _get_dist_time(self, id1, id2):
        return self.dist_matrix.get((id1, id2), 0)

    def _precompute_distances(self):
        all_nodes = self.pois + [self.hotel]
        for p1 in all_nodes:
            for p2 in all_nodes:
                if p1['id'] == p2['id']: continue
                dist = geodesic((p1['lat'], p1['lon']), (p2['lat'], p2['lon'])).km
                
                if p1.get('type') == 'hotel': speed = DRIVING_SPEED_KMH
                else: speed = WALKING_SPEED_KMH
                
                self.dist_matrix[(p1['id'], p2['id'])] = int((dist / speed) * 60)

    def _evaluate_schedule(self, ordered_pois):
        schedule = []
        pendentes = ordered_pois.copy()
        total_travel = 0
        visited_count = 0
        dia = 1
        
        while pendentes and dia <= 10:
            # Manhã
            loc_atual = self.hotel
            tempo_gasto = 0
            manha_pois = []
            i = 0
            while i < len(pendentes):
                poi = pendentes[i]
                travel = self._get_dist_time(loc_atual['id'], poi['id'])
                cost = travel + poi['time_min']
                if (tempo_gasto + cost) <= self.max_min_manha:
                    p = poi.copy()
                    p.update({'day': dia, 'period': 'Manhã', 'transit_prev': travel})
                    manha_pois.append(p)
                    tempo_gasto += cost; total_travel += travel; loc_atual = poi; visited_count += 1
                    pendentes.pop(i)
                else: i += 1
            
            # Tarde
            loc_atual = manha_pois[-1] if manha_pois else self.hotel
            tempo_gasto = 0
            tarde_pois = []
            i = 0
            while i < len(pendentes):
                poi = pendentes[i]
                travel = self._get_dist_time(loc_atual['id'], poi['id'])
                cost = travel + poi['time_min']
                if (tempo_gasto + cost) <= self.max_min_tarde:
                    p = poi.copy()
                    p.update({'day': dia, 'period': 'Tarde', 'transit_prev': travel})
                    tarde_pois.append(p)
                    tempo_gasto += cost; total_travel += travel; loc_atual = poi; visited_count += 1
                    pendentes.pop(i)
                else: i += 1
            
            if manha_pois or tarde_pois:
                schedule.extend(manha_pois + tarde_pois)
                dia += 1
            else: break
        return schedule, visited_count, total_travel

    def solve_simulated_annealing(self, iterations=3000, temp=1000, cooling_rate=0.995):
        current_solution = self.pois.copy()
        random.shuffle(current_solution)
        current_sched, curr_vis, curr_trav = self._evaluate_schedule(current_solution)
        current_energy = -(curr_vis * 10000) + curr_trav
        
        best_solution = current_solution[:]
        best_energy = current_energy
        best_schedule = current_sched
        
        for i in range(iterations):
            new_solution = current_solution[:]
            idx1, idx2 = random.sample(range(len(new_solution)), 2)
            new_solution[idx1], new_solution[idx2] = new_solution[idx2], new_solution[idx1]
            
            new_sched, new_vis, new_trav = self._evaluate_schedule(new_solution)
            new_energy = -(new_vis * 10000) + new_trav
            
            delta = new_energy - current_energy
            if delta < 0 or random.random() < math.exp(-delta / temp):
                current_solution = new_solution
                current_energy = new_energy
                if new_energy < best_energy:
                    best_energy = new_energy
                    best_schedule = new_sched
            temp *= cooling_rate
            
        final_list = [{'id': self.hotel['id'], 'name': self.hotel['name'], 'lat': self.hotel['lat'], 'lon': self.hotel['lon'], 'type': 'hotel', 'day': 0, 'period': 'Base', 'time_min': 0}]
        final_list.extend(best_schedule)
        
        visited_ids = set(p['id'] for p in best_schedule)
        for p in self.pois:
            if p['id'] not in visited_ids:
                pc = p.copy(); pc.update({'day': 0, 'period': '-'}); final_list.append(pc)
        return final_list

def run_optimization_logic(pois, max_h_manha, max_h_tarde):
    hotel = next((p for p in pois if p.get('type') == 'hotel'), None)
    visit_pois = [p for p in pois if p.get('type') == 'visit']
    
    if not hotel: return None, "Defina um Hotel/Base."
    if not visit_pois: return pois, "Adicione locais do tipo 'Visita' para gerar roteiro."
    
    optimizer = TravelOptimizer(visit_pois, hotel, max_h_manha, max_h_tarde)
    optimized_schedule = optimizer.solve_simulated_annealing()
    msg = "Otimização concluída!"

    optimized_ids = set(p['id'] for p in optimized_schedule)
    others = [p for p in pois if p['id'] not in optimized_ids]
    for o in others:
        o['day'] = 0
        o['period'] = '-'
    
    return optimized_schedule + others, msg

# --- UI COMPONENTS ---

def render_sidebar_login():
    """Gerencia a autenticação na barra lateral."""
    if 'authenticated' not in st.session_state:
        st.session_state['authenticated'] = False

    with st.sidebar:
        st.header("🔒 Acesso Admin")
        
        if not st.session_state['authenticated']:
            password = st.text_input("Senha de Admin", type="password")
            if st.button("Entrar"):
                if password == ADMIN_PASSWORD:
                    st.session_state['authenticated'] = True
                    st.success("Login efetuado!")
                    st.rerun()
                else:
                    st.error("Senha incorreta.")
            st.info("Modo: 👀 Apenas Leitura")
        else:
            st.success("✅ Autenticado (Modo Edição)")
            if st.button("Sair / Logout"):
                st.session_state['authenticated'] = False
                st.rerun()

def render_dashboard():
    st.title("🌍 AI Travel Planner")
    st.caption("Suporta pesquisa de locais (OSM) e coordenadas decimais.")
    st.markdown("---")

    if st.session_state.get('authenticated'):
        with st.expander("➕ Adicionar Novo Destino", expanded=False):
            with st.form("new_city_form"):
                c_name = st.text_input("Nome da Cidade")
                c1, c2 = st.columns(2)
                raw_lat = c1.text_input("Latitude", placeholder="Decimal ou DMS")
                raw_lon = c2.text_input("Longitude", placeholder="Decimal ou DMS")
                c_img = st.text_input("URL da Imagem", placeholder="https://...")
                
                if st.form_submit_button("Criar Destino"):
                    lat_float = parse_coordinate(raw_lat)
                    lon_float = parse_coordinate(raw_lon)

                    if c_name and lat_float is not None and lon_float is not None:
                        cid = str(uuid.uuid4())
                        st.session_state['cities'][cid] = {
                            "id": cid, "name": c_name, "lat": lat_float, "lon": lon_float, 
                            "img": c_img if c_img else "https://via.placeholder.com/300x150", "pois": []
                        }
                        save_data()
                        st.success(f"Destino criado em {lat_float}, {lon_float}")
                        st.rerun()
                    else:
                        st.error("Erro nas coordenadas ou nome vazio.")
    else:
        st.info("🔒 Faça login na barra lateral para adicionar novos destinos.")

    st.subheader("Meus Destinos")
    if not st.session_state['cities']:
        st.info("Nenhuma cidade adicionada ainda.")
        return

    cols = st.columns(3)
    city_items = list(st.session_state['cities'].items())

    for idx, (cid, city) in enumerate(city_items):
        with cols[idx % 3].container(border=True):
            st.image(city['img'])
            st.markdown(f"### {city['name']}")
            
            if st.session_state.get('authenticated'):
                col_plan, col_del = st.columns([4, 1])
            else:
                col_plan = st.container()

            with col_plan:
                if st.button(f"Planear", key=f"btn_plan_{cid}", use_container_width=True):
                    st.session_state['selected_city_id'] = cid
                    st.rerun()
            
            if st.session_state.get('authenticated'):
                with col_del:
                    if st.button("🗑️", key=f"btn_del_{cid}", help="Apagar destino"):
                        del st.session_state['cities'][cid]
                        save_data(); st.toast("Removido!"); st.rerun()

def render_stylish_card(poi, city_id, is_first=False):
    is_auth = st.session_state.get('authenticated', False)

    if not is_first and 'transit_prev' in poi and poi['transit_prev'] > 0 and poi.get('day', 0) > 0:
        icon_transit = "🚗" if poi.get('transit_prev') > 45 else "🚶"
        st.markdown(f"""
        <div style="text-align: center; color: #888; font-size: 0.8em; margin: 5px 0;">
            ⋮<br>{icon_transit} <i>{poi['transit_prev']} min deslocamento</i><br>⋮
        </div>
        """, unsafe_allow_html=True)

    with st.container(border=True):
        if is_auth:
            col_icon, col_info, col_move, col_action = st.columns([0.8, 4, 2, 0.5])
        else:
            col_icon, col_info, col_move = st.columns([0.8, 4, 2])

        with col_icon:
            p_type = poi.get('type', 'visit')
            icon_char = "📍"
            if p_type == 'hotel': icon_char = "🏨"
            elif p_type == 'food': icon_char = "🍴"
            elif p_type == 'transport': icon_char = "✈️"
            st.markdown(f"<div style='font-size: 2.2em; text-align: center; padding-top: 5px;'>{icon_char}</div>", unsafe_allow_html=True)
        
        with col_info:
            st.markdown(f"**{poi['name']}**")
            tags = []
            type_label = TYPE_CONFIG.get(poi.get('type', 'visit'), {}).get('label', 'Local')
            tags.append(f"{type_label}")
            if poi.get('type') == 'visit': tags.append(f"⏱️ {poi['time_min']} min")
            if poi.get('cost', 0) > 0: tags.append(f"💶 {poi['cost']}€")
            
            if tags:
                tags_html = "".join([f"<span style='background-color: #f0f2f6; padding: 2px 8px; border-radius: 12px; font-size: 0.75em; margin-right: 5px; color: #444; border: 1px solid #e0e0e0;'>{t}</span>" for t in tags])
                st.markdown(tags_html, unsafe_allow_html=True)
            if poi.get('desc'): st.caption(poi['desc'][:60] + "...")

        with col_move:
            if poi.get('type') != 'hotel':
                current_val_str = "📌 Não Agendado"
                if poi.get('day', 0) > 0:
                    current_val_str = f"Dia {poi['day']} - {poi.get('period', 'Manhã')}"

                if is_auth:
                    all_pois = st.session_state['cities'][city_id]['pois']
                    max_day = max([p.get('day', 0) for p in all_pois] + [0])
                    limit_day = max(max_day + 1, 3)
                    
                    move_options = {"📌 Não Agendado": (0, '-')}
                    ordered_keys = ["📌 Não Agendado"]
                    for d in range(1, limit_day + 1):
                        for per in ['Manhã', 'Tarde']:
                            key_str = f"Dia {d} - {per}"
                            ordered_keys.append(key_str)
                            move_options[key_str] = (d, per)
                    
                    if current_val_str not in ordered_keys:
                        ordered_keys.append(current_val_str)
                        move_options[current_val_str] = (poi['day'], poi.get('period', '-'))

                    selected_opt = st.selectbox("Mover", options=ordered_keys, index=ordered_keys.index(current_val_str), key=f"mv_{poi['id']}", label_visibility="collapsed")

                    if selected_opt != current_val_str:
                        new_day, new_period = move_options[selected_opt]
                        target_poi = next(p for p in st.session_state['cities'][city_id]['pois'] if p['id'] == poi['id'])
                        target_poi['day'] = new_day
                        target_poi['period'] = new_period
                        save_data(); st.rerun()
                else:
                    st.markdown(f"<div style='margin-top: 5px; font-size: 0.9em; color: #666;'>{current_val_str}</div>", unsafe_allow_html=True)
            else:
                st.caption("Base Fixa")

        if is_auth:
            with col_action:
                st.write("")
                if st.button("🗑️", key=f"del_sty_{poi['id']}", help="Remover"):
                    st.session_state['cities'][city_id]['pois'] = [p for p in st.session_state['cities'][city_id]['pois'] if p['id'] != poi['id']]
                    save_data(); st.rerun()

def render_city_planner(city_id):
    if city_id not in st.session_state['cities']:
        st.session_state['selected_city_id'] = None; st.rerun(); return

    city = st.session_state['cities'][city_id]
    is_auth = st.session_state.get('authenticated', False)
    
    if 'swap_source' not in st.session_state: st.session_state['swap_source'] = None
    if 'new_poi_name' not in st.session_state: st.session_state['new_poi_name'] = ""
    if 'new_poi_lat' not in st.session_state: st.session_state['new_poi_lat'] = str(city['lat'])
    if 'new_poi_lon' not in st.session_state: st.session_state['new_poi_lon'] = str(city['lon'])

    c1, c2 = st.columns([1, 6])
    if c1.button("⬅ Voltar"):
        st.session_state['selected_city_id'] = None; st.rerun()
    c2.title(city['name'])

    col_map, col_data = st.columns([1.5, 1])

    with col_map:
        # --- FILTRO DE VISUALIZAÇÃO DE MAPA ---
        active_days = sorted(list(set(p['day'] for p in city['pois'] if p.get('day', 0) > 0)))
        filter_options = ["Todos"] + [f"Dia {d}" for d in active_days]
        
        c_filter, _ = st.columns([2, 1])
        selected_view = c_filter.radio("Visualizar Rota:", filter_options, horizontal=True)

        DAY_COLORS = ['green', 'purple', 'orange', 'red', 'darkblue', 'cadetblue', 'darkred']
        m = folium.Map([city['lat'], city['lon']], zoom_start=13)
        
        # Determinar qual o dia a filtrar (0 se Todos)
        filter_day_int = 0
        if selected_view.startswith("Dia"):
            filter_day_int = int(selected_view.split(" ")[1])

        # Adicionar Marcadores
        for p in city['pois']:
            p_type = p.get('type', 'visit')
            day = p.get('day', 0)
            
            # Lógica de Filtro:
            # Se Todos: mostra tudo.
            # Se Dia X: mostra Hotel + POIs do Dia X. Esconde o resto.
            show_poi = True
            if filter_day_int > 0:
                if p_type == 'hotel': show_poi = True
                elif day == filter_day_int: show_poi = True
                else: show_poi = False
            
            if show_poi:
                color = TYPE_CONFIG.get(p_type, {}).get('color', 'blue')
                icon_name = TYPE_CONFIG.get(p_type, {}).get('icon', 'info-sign')
                if p_type == 'visit' and day > 0: color = DAY_COLORS[(day - 1) % len(DAY_COLORS)]
                
                # Highlight selection for swap
                if st.session_state['swap_source'] == p['id']:
                    icon_name = 'star'
                    color = 'gold'
                    
                folium.Marker([p['lat'], p['lon']], popup=f"{p['name']}", icon=folium.Icon(color=color, icon=icon_name, prefix='fa')).add_to(m)
        
        # Adicionar Polylines (Rotas)
        visit_pois = [p for p in city['pois'] if p.get('day', 0) > 0 and p.get('type') == 'visit']
        days = sorted(list(set(p['day'] for p in visit_pois)))
        hotel = next((p for p in city['pois'] if p.get('type')=='hotel'), None)
        
        for d in days:
            # Se estiver a filtrar por dia, só desenha a linha desse dia
            if filter_day_int == 0 or filter_day_int == d:
                pts = [p for p in city['pois'] if p.get('day') == d and p.get('type') == 'visit']
                coords = []
                if hotel: coords.append([hotel['lat'], hotel['lon']])
                coords.extend([[p['lat'], p['lon']] for p in pts])
                if hotel: coords.append([hotel['lat'], hotel['lon']])
                
                if len(coords) > 1:
                    line_color = DAY_COLORS[(d - 1) % len(DAY_COLORS)]
                    folium.PolyLine(coords, color=line_color, weight=5, opacity=0.8, tooltip=f"Rota Dia {d}").add_to(m)
            
        map_data = st_folium(m, height=500, use_container_width=True)
        
        # --- LÓGICA DE MAPA: CLIQUE & SWAP ---
        clicked_poi = None
        if is_auth and map_data:
            if map_data.get('last_object_clicked'):
                lat_click = map_data['last_object_clicked']['lat']
                lon_click = map_data['last_object_clicked']['lng']
                for p in city['pois']:
                    if math.isclose(p['lat'], lat_click, abs_tol=0.0001) and math.isclose(p['lon'], lon_click, abs_tol=0.0001):
                        clicked_poi = p; break

            if map_data.get("last_clicked") and not clicked_poi:
                new_lat = str(map_data["last_clicked"]["lat"])
                new_lon = str(map_data["last_clicked"]["lng"])
                if new_lat != st.session_state['new_poi_lat'] or new_lon != st.session_state['new_poi_lon']:
                    st.session_state['new_poi_lat'] = new_lat
                    st.session_state['new_poi_lon'] = new_lon
                    st.rerun()

        if clicked_poi and is_auth:
            with st.container(border=True):
                st.info(f"📍 Selecionado: **{clicked_poi['name']}**")
                
                c_swap, c_del = st.columns(2)
                with c_swap:
                    if st.session_state['swap_source'] is None:
                        if st.button("🔄 Selecionar p/ Troca"):
                            st.session_state['swap_source'] = clicked_poi['id']
                            st.rerun()
                    else:
                        if st.session_state['swap_source'] == clicked_poi['id']:
                            if st.button("❌ Cancelar Seleção"):
                                st.session_state['swap_source'] = None
                                st.rerun()
                        else:
                            source_p = next((p for p in city['pois'] if p['id'] == st.session_state['swap_source']), None)
                            if source_p:
                                if st.button(f"🔀 Trocar com '{source_p['name']}'"):
                                    idx_source = city['pois'].index(source_p)
                                    idx_target = city['pois'].index(clicked_poi)
                                    city['pois'][idx_source], city['pois'][idx_target] = city['pois'][idx_target], city['pois'][idx_source]
                                    city['pois'][idx_source]['day'], city['pois'][idx_target]['day'] = city['pois'][idx_target]['day'], city['pois'][idx_source]['day']
                                    city['pois'][idx_source]['period'], city['pois'][idx_target]['period'] = city['pois'][idx_target]['period'], city['pois'][idx_source]['period']
                                    st.session_state['swap_source'] = None
                                    save_data()
                                    st.success("Trocado!")
                                    st.rerun()

                with c_del:
                    if st.button("🗑️ Eliminar", key=f"del_map_{clicked_poi['id']}", type="primary"):
                        st.session_state['cities'][city_id]['pois'] = [p for p in city['pois'] if p['id'] != clicked_poi['id']]
                        save_data(); st.rerun()

    with col_data:
        tabs = st.tabs(["📝 Novo Local", "📅 Roteiro", "⚙️ Otimizar", "📄 PDF"])
        
        # --- ABA 1: NOVO LOCAL ---
        with tabs[0]:
            if is_auth:
                st.markdown("##### 🔍 Pesquisa & Adição")
                c_search, c_btn = st.columns([3, 1])
                search_query = c_search.text_input("Pesquisar Local", label_visibility="collapsed")
                if c_btn.button("🔍") and search_query:
                    with st.spinner("A pesquisar..."):
                        s_lat, s_lon, s_addr = search_place_nominatim(search_query)
                        if s_lat:
                            st.session_state['new_poi_name'] = search_query
                            st.session_state['new_poi_lat'] = str(s_lat)
                            st.session_state['new_poi_lon'] = str(s_lon)
                            st.success(f"Encontrado: {s_addr[:40]}...")
                            st.rerun()
                        else: st.error("Não encontrado.")

                st.markdown("---")
                
                type_options = list(TYPE_CONFIG.keys())
                label_to_key = {v['label']: k for k, v in TYPE_CONFIG.items()}
                selected_label = st.selectbox("Tipo", list(label_to_key.keys()), index=1)
                selected_type = label_to_key[selected_label]
                
                name = st.text_input("Nome", key="new_poi_name")
                
                c_addr_in, c_addr_btn = st.columns([3, 1])
                addr_manual = c_addr_in.text_input("address_manual", label_visibility="collapsed", placeholder="Morada Manual...")
                if c_addr_btn.button("📍", help="Buscar coords"):
                    if addr_manual:
                        a_lat, a_lon, _ = search_place_nominatim(addr_manual)
                        if a_lat:
                            st.session_state['new_poi_lat'] = str(a_lat)
                            st.session_state['new_poi_lon'] = str(a_lon)
                            if not name: st.session_state['new_poi_name'] = addr_manual
                            st.rerun()

                c_lat, c_lon = st.columns(2)
                raw_lat_poi = c_lat.text_input("Lat", key="new_poi_lat")
                raw_lon_poi = c_lon.text_input("Lon", key="new_poi_lon")
                
                time_val = 60
                if selected_type == 'visit': time_val = st.number_input("Duração (min)", value=60)
                cost = st.number_input("Custo (€)", value=0.0)
                
                if st.button("💾 Salvar Local", type="primary", use_container_width=True):
                    lat_final = parse_coordinate(raw_lat_poi)
                    lon_final = parse_coordinate(raw_lon_poi)
                    
                    if (lat_final is None or lon_final is None) and addr_manual:
                         l, lo, _ = search_place_nominatim(addr_manual)
                         if l: lat_final, lon_final = l, lo

                    if lat_final is not None and lon_final is not None:
                        if selected_type == 'hotel':
                            for p in city['pois']: 
                                if p.get('type')=='hotel': p['type']='visit'
                        
                        city['pois'].append({
                            "id":str(uuid.uuid4()), "name":name if name else (addr_manual if addr_manual else "Sem Nome"), 
                            "lat":lat_final, "lon":lon_final, "time_min":time_val, 
                            "cost":cost, "type":selected_type, "day":0
                        })
                        save_data(); st.success("Adicionado!"); st.rerun()
                    else: st.error("Coordenadas inválidas.")

                st.markdown("---")
                if st.button("🗑️ Remover TODOS os locais", type="primary"):
                    city['pois'] = []; save_data(); st.rerun()
            else:
                st.warning("🔒 Modo Leitura. Faça login para editar.")

        # --- ABA 2: ROTEIRO ---
        with tabs[1]:
            st.markdown("""<style>.stExpander { border: none !important; box-shadow: none !important; } .element-container { margin-bottom: 0.5rem; }</style>""", unsafe_allow_html=True)
            visitas = [p for p in city['pois'] if p.get('type')!='hotel']
            days = sorted(list(set(p.get('day',0) for p in city['pois'] if p.get('day', 0) > 0)))
            hotel = next((p for p in city['pois'] if p.get('type') == 'hotel'), None)
            
            if hotel:
                with st.container(border=True):
                    c_h1, c_h2 = st.columns([1, 5])
                    with c_h1: st.markdown("<div style='font-size: 2em; text-align:center;'>🏨</div>", unsafe_allow_html=True)
                    with c_h2: st.markdown(f"**Base: {hotel['name']}**"); st.caption("Ponto de partida")

            if not days and not visitas: st.info("O roteiro está vazio.")
            
            for d in days:
                st.markdown("<br>", unsafe_allow_html=True)
                p_dia = [x for x in city['pois'] if x.get('day')==d and x.get('type') == 'visit']
                total_min = sum(p.get('time_min',0) for p in p_dia)
                st.markdown(f"""<div style="background-color: #f0f8ff; padding: 15px; border-radius: 10px; border-left: 5px solid #007bff; margin-bottom: 20px;">
                        <h4 style="margin:0; color: #004085;">🗓️ Dia {d}</h4>
                        <span style="font-size: 0.9em; color: #555;">{len(p_dia)} Locais • {total_min//60}h {total_min%60}m</span>
                    </div>""", unsafe_allow_html=True)
                
                for per_name, per_icon in [('Manhã', '🌅'), ('Tarde', '🌇')]:
                    p_per = [x for x in p_dia if x.get('period') == per_name]
                    if p_per:
                        st.markdown(f"##### {per_icon} {per_name}")
                        for idx, p in enumerate(p_per):
                            is_first_item = (idx == 0) and (per_name == 'Manhã' or not [x for x in p_dia if x.get('period') == 'Manhã'])
                            render_stylish_card(p, city_id, is_first=is_first_item)
                        st.markdown("<br>", unsafe_allow_html=True)

            unscheduled = [x for x in city['pois'] if x.get('day', 0) == 0 and x.get('type') != 'hotel']
            if unscheduled:
                st.markdown("---")
                with st.expander(f"📌 **Itens Não Agendados ({len(unscheduled)})**", expanded=True):
                    for tipo_code in ['visit', 'food', 'transport']:
                        grupo = [x for x in unscheduled if x.get('type') == tipo_code]
                        if grupo:
                            st.caption(f"**{TYPE_CONFIG[tipo_code]['label']}**")
                            for p in grupo: render_stylish_card(p, city_id, is_first=True)

        # --- ABA 3: OTIMIZAR ---
        with tabs[2]:
            if is_auth:
                st.write("#### AI Optimizer")
                st.caption(f"Simulated Annealing | Tolerância: {TOLERANCIA_MINUTOS}min")
                c1, c2 = st.columns(2)
                hm = c1.number_input("Horas Manhã", 1, 8, 4)
                ht = c2.number_input("Horas Tarde", 1, 8, 4)
                if st.button("🚀 Otimizar", use_container_width=True):
                    with st.spinner("Otimizando rota..."):
                        res, msg = run_optimization_logic(city['pois'], hm, ht)
                        if res:
                            st.session_state['cities'][city_id]['pois'] = res
                            save_data(); st.success(msg); st.rerun()
                        else: st.error(msg)
            else:
                st.warning("🔒 Login necessário para otimização automática.")

        # --- ABA 4: PDF ---
        with tabs[3]:
            st.header("📄 Exportar Roteiro")
            st.info("Para obter o mapa no PDF: Use o filtro 'Visualizar Rota' acima do mapa para isolar cada dia, tire um print screen e carregue a imagem aqui.")
            
            # Identificar dias ativos
            visit_pois = [p for p in city['pois'] if p.get('day', 0) > 0 and p.get('type') == 'visit']
            active_days_pdf = sorted(list(set(p['day'] for p in visit_pois)))
            
            uploaded_maps = {}
            
            if not active_days_pdf:
                st.warning("Nenhum roteiro definido. Adicione visitas a dias para gerar o PDF.")
            else:
                for day in active_days_pdf:
                    uploaded_maps[day] = st.file_uploader(f"📸 Imagem do Mapa - Dia {day}", type=['png', 'jpg', 'jpeg'], key=f"uploader_{day}")
                
                st.markdown("---")
                if st.button("🖨️ Gerar PDF"):
                    with st.spinner("A gerar documento..."):
                        try:
                            pdf_bytes = generate_pdf(city, uploaded_maps)
                            st.download_button(
                                label="📥 Baixar PDF",
                                data=pdf_bytes,
                                file_name=f"roteiro_{city['name']}.pdf",
                                mime="application/pdf"
                            )
                        except Exception as e:
                            st.error(f"Erro ao gerar PDF: {e}")

# --- MAIN ---
if 'cities' not in st.session_state: st.session_state['cities'] = load_data()
if 'selected_city_id' not in st.session_state: st.session_state['selected_city_id'] = None

render_sidebar_login()

if st.session_state['selected_city_id']:
    render_city_planner(st.session_state['selected_city_id'])
else:
    render_dashboard()